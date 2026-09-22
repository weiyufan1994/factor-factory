from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import factor_factory.console.evo_child_runtime as child_runtime
import factor_factory.evo_child_preregistration as child_preregistration
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store

from factor_factory.console.web_factor_proof import (
    validate_web_factor_proof_preregistration,
)
from factor_factory.evo_oos import (
    OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
    _allocate_fresh_child_oos,
    build_and_allocate_fresh_child_oos,
    consume_oos_allocation_for_release,
    oos_allocation_path,
    oos_allocation_receipt_path,
    oos_registry_path,
    validate_child_oos_finalizer_authority,
    validate_oos_release_authorization,
    validate_oos_release_consumption,
    validate_oos_release_preflight,
)
from factor_factory.oos_exposure_incident import (
    BLOCK_OOS_EXPOSURE_INCIDENT,
    OOS_EXPOSURE_INCIDENT_AUTHORITY,
    OOS_EXPOSURE_INSTALLATION_ID_ENV,
    OOS_EXPOSURE_TRUST_ROOT_ENV,
    build_oos_exposure_incident,
    build_oos_exposure_provenance_addendum,
    commit_oos_exposure_incident_host_private,
    ensure_empty_oos_exposure_private_registry,
    load_and_validate_oos_exposure_incident,
    load_and_validate_oos_exposure_provenance_addendum,
    oos_exposure_incident_block_reasons,
    oos_exposure_incident_path,
    oos_exposure_private_registry_path,
    oos_exposure_private_registry_guard,
    prepare_oos_exposure_incident_host_private,
    record_oos_exposure_incident_durable,
    register_oos_exposure_incident_host_private,
    validate_oos_exposure_incident,
    validate_oos_exposure_private_registry_guard,
    write_oos_exposure_incident_create_only,
    write_oos_exposure_provenance_addendum_create_only,
)


REPORT_ID = "NEG_PV_TEST_REPORT"
FACTOR_ID = "NEGATIVE_PRICE_VOLUME_TEST_V1"
TOKEN = "a" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


def _artifact(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / "evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _payload(tmp_path: Path) -> dict:
    return build_oos_exposure_incident(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        factor_id=FACTOR_ID,
        frozen_oos_start="2022-09-02",
        frozen_oos_end="2025-07-11",
        frozen_oos_release_token_sha256=TOKEN,
        exposed_overlap_start="2025-01-02",
        exposed_overlap_end="2025-07-11",
        exposed_row_count=676_659,
        exposed_period_count=126,
        source_path=_artifact(tmp_path, "daily.csv", "source"),
        panel_path=_artifact(tmp_path, "panel.parquet", "panel"),
        metrics_path=_artifact(tmp_path, "metrics.json", "metrics"),
        runner_path=_artifact(tmp_path, "runner.py", "runner"),
        incident_at="2026-08-13T06:00:00Z",
    )


def _minimal_plan() -> dict:
    return {
        "identity": {
            "report_id": REPORT_ID,
            "factor_id": FACTOR_ID,
            "research_id": "research_test_001",
        }
    }


def test_private_registry_guard_rejects_unissued_object(tmp_path: Path) -> None:
    trust_root = tmp_path / "trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-object-test")

    with pytest.raises(ValueError, match="private_registry_guard_invalid"):
        validate_oos_exposure_private_registry_guard(
            object(),
            trust_root=trust_root,
            installation_id="guard-object-test",
        )


def test_private_registry_guard_expires_at_context_exit(tmp_path: Path) -> None:
    trust_root = tmp_path / "trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-lifetime-test")

    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id="guard-lifetime-test",
    ) as guard:
        validate_oos_exposure_private_registry_guard(
            guard,
            trust_root=trust_root,
            installation_id="guard-lifetime-test",
        )

    with pytest.raises(ValueError, match="private_registry_guard_invalid"):
        validate_oos_exposure_private_registry_guard(
            guard,
            trust_root=trust_root,
            installation_id="guard-lifetime-test",
        )


def test_private_registry_guard_is_bound_to_host_identity(tmp_path: Path) -> None:
    trust_root = tmp_path / "trust"
    other_trust_root = tmp_path / "other-trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-host-test")
    ensure_runtime_trust_store(other_trust_root, installation_id="guard-host-test")

    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id="guard-host-test",
    ) as guard:
        with pytest.raises(ValueError, match="host_binding"):
            validate_oos_exposure_private_registry_guard(
                guard,
                trust_root=other_trust_root,
                installation_id="guard-host-test",
            )
        with pytest.raises(ValueError, match="host_binding"):
            validate_oos_exposure_private_registry_guard(
                guard,
                trust_root=trust_root,
                installation_id="guard-host-test-other",
            )


def test_private_registry_guard_is_bound_to_registry_head(tmp_path: Path) -> None:
    trust_root = tmp_path / "trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-head-test")

    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id="guard-head-test",
    ) as guard:
        anchor_path = oos_exposure_private_registry_path(trust_root).with_name(
            "registry.anchor.json"
        )
        anchor_path.write_text(
            anchor_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="head_binding"):
            validate_oos_exposure_private_registry_guard(
                guard,
                trust_root=trust_root,
                installation_id="guard-head-test",
            )


def test_current_validator_reuses_same_active_guard_without_relocking(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trust_root = tmp_path / "trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-nested-test")

    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id="guard-nested-test",
    ) as guard:
        assert validate_oos_release_authorization(
            workspace_root=workspace,
            report_id=REPORT_ID,
            oos_window={"start": "2026-01-01", "end": "2026-03-31"},
            sealed_token_sha256=TOKEN,
            incident_trust_root=trust_root,
            incident_installation_id="guard-nested-test",
            _incident_guard=guard,
        ) == []


def test_current_validator_without_active_guard_reenters_registry_lock(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trust_root = tmp_path / "trust"
    ensure_runtime_trust_store(trust_root, installation_id="guard-relock-test")
    ensure_empty_oos_exposure_private_registry(
        trust_root,
        installation_id="guard-relock-test",
    )
    script = f"""
from pathlib import Path
from factor_factory.evo_oos import validate_oos_release_authorization
from factor_factory.oos_exposure_incident import oos_exposure_private_registry_guard

workspace = Path({str(workspace)!r})
trust_root = Path({str(trust_root)!r})
with oos_exposure_private_registry_guard(
    trust_root,
    installation_id="guard-relock-test",
):
    validate_oos_release_authorization(
        workspace_root=workspace,
        report_id={REPORT_ID!r},
        oos_window={{"start": "2026-01-01", "end": "2026-03-31"}},
        sealed_token_sha256={TOKEN!r},
        incident_trust_root=trust_root,
        incident_installation_id="guard-relock-test",
    )
"""
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=1.0,
        )


def test_valid_marker_is_closed_self_hashed_negative_evidence(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    assert validate_oos_exposure_incident(payload) == []
    result = write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=payload,
    )
    assert result["status"] == "CREATED_NEGATIVE_EVIDENCE"
    assert result["authority"] == OOS_EXPOSURE_INCIDENT_AUTHORITY
    assert result["formal_oos_eligible"] is False
    assert load_and_validate_oos_exposure_incident(tmp_path, REPORT_ID) == payload

    extra = {**payload, "unexpected": True}
    assert f"{BLOCK_OOS_EXPOSURE_INCIDENT}:shape" in (
        validate_oos_exposure_incident(extra)
    )


def test_marker_presence_blocks_release_finalizer_and_web_preregistration(
    tmp_path: Path,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    expected = f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_present"

    assert validate_oos_release_authorization(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        oos_window={"start": "2022-09-02", "end": "2025-07-11"},
        sealed_token_sha256=TOKEN,
    ) == [expected]
    assert validate_oos_release_preflight(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        release_manifest_payload={},
    ) == [expected]
    assert validate_child_oos_finalizer_authority(
        workspace_root=tmp_path,
        parent_report_id="PARENT_REPORT_001",
        child_report_id=REPORT_ID,
        allocation_id="allocation_test_001",
    ) == [expected]
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        consume_oos_allocation_for_release(
            workspace_root=tmp_path,
            report_id=REPORT_ID,
            release_manifest_path=tmp_path / "release.json",
        )
    assert validate_oos_release_consumption(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        release_manifest_path=tmp_path / "release.json",
    ) == [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_present"]
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        validate_web_factor_proof_preregistration(tmp_path, _minimal_plan())


@pytest.mark.parametrize("kind", ["invalid", "symlink", "broken_symlink"])
def test_invalid_or_symlink_marker_still_blocks_formal_oos(
    tmp_path: Path,
    kind: str,
) -> None:
    marker = oos_exposure_incident_path(tmp_path, REPORT_ID)
    marker.parent.mkdir(parents=True, exist_ok=True)
    if kind == "invalid":
        marker.write_text("{invalid", encoding="utf-8")
    else:
        target = tmp_path / ("target.json" if kind == "symlink" else "missing.json")
        if kind == "symlink":
            target.write_text(json.dumps(_payload(tmp_path)), encoding="utf-8")
        marker.symlink_to(target)

    expected = f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_present"
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [expected]
    assert validate_oos_release_authorization(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        oos_window="2022-09-02/2025-07-11",
        sealed_token_sha256=TOKEN,
    ) == [expected]
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        validate_web_factor_proof_preregistration(tmp_path, _minimal_plan())


def test_writer_is_exactly_idempotent_and_tamper_refusing(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    first = write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=payload,
    )
    second = write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=payload,
    )
    assert first["status"] == "CREATED_NEGATIVE_EVIDENCE"
    assert second["status"] == "IDEMPOTENT_EXACT"

    marker = oos_exposure_incident_path(tmp_path, REPORT_ID)
    tampered = dict(payload)
    tampered["exposed_row_count"] = 1
    marker.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="marker_conflict_tamper"):
        write_oos_exposure_incident_create_only(
            workspace_root=tmp_path,
            payload=payload,
        )


def test_writer_never_grants_authority_and_rejects_self_hash_tamper(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    payload["formal_oos_eligible"] = True
    assert f"{BLOCK_OOS_EXPOSURE_INCIDENT}:formal_oos_eligible" in (
        validate_oos_exposure_incident(payload)
    )
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        write_oos_exposure_incident_create_only(
            workspace_root=tmp_path,
            payload=payload,
        )


def test_low_level_allocation_entry_blocks_before_trust_or_writes(
    tmp_path: Path,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        _allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_test_001",
            report_id=REPORT_ID,
            parent_report_id="PARENT_REPORT_001",
            dataset_snapshot_sha256="b" * 64,
            oos_start="2026-01-01",
            oos_end="2026-03-31",
            sealed_token_sha256="c" * 64,
            allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
            expected_registry_sha256=None,
            trust_root=tmp_path / "nonexistent_private_trust",
            installation_id="installation_test_001",
        )
    assert not (tmp_path / "objects/research_protocol/evo_oos_allocation_registry.json").exists()


@pytest.mark.parametrize("kind", ["valid", "invalid", "symlink", "broken_symlink"])
def test_host_carrier_allocator_blocks_marker_before_carrier_read(
    tmp_path: Path,
    kind: str,
) -> None:
    marker = oos_exposure_incident_path(tmp_path, REPORT_ID)
    marker.parent.mkdir(parents=True, exist_ok=True)
    if kind == "valid":
        write_oos_exposure_incident_create_only(
            workspace_root=tmp_path,
            payload=_payload(tmp_path),
        )
    elif kind == "invalid":
        marker.write_text("not-json", encoding="utf-8")
    else:
        target = tmp_path / ("marker_target.json" if kind == "symlink" else "missing.json")
        if kind == "symlink":
            target.write_text("{}", encoding="utf-8")
        marker.symlink_to(target)

    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        build_and_allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_test_001",
            report_id=REPORT_ID,
            parent_report_id="PARENT_REPORT_001",
            oos_start="2026-01-01",
            oos_end="2026-03-31",
            sealed_oos_carrier_path=tmp_path / "must_not_be_opened.carrier",
            sealed_oos_private_root=tmp_path / "must_not_be_opened",
            expected_registry_sha256=None,
            trust_root=tmp_path / "must_not_be_opened_trust",
            installation_id="installation_test_001",
        )
    assert not (tmp_path / "objects/research_protocol/evo_oos_allocation_registry.json").exists()


def test_parent_incident_cannot_be_laundered_into_child_allocation(
    tmp_path: Path,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    with pytest.raises(ValueError, match=BLOCK_OOS_EXPOSURE_INCIDENT):
        build_and_allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_child_001",
            report_id="FRESH_CHILD_REPORT_001",
            parent_report_id=REPORT_ID,
            oos_start="2026-01-01",
            oos_end="2026-03-31",
            sealed_oos_carrier_path=tmp_path / "must_not_be_opened.carrier",
            sealed_oos_private_root=tmp_path / "must_not_be_opened",
            expected_registry_sha256=None,
            trust_root=tmp_path / "must_not_be_opened_trust",
            installation_id="installation_test_001",
        )


def test_create_only_provenance_addendum_corrects_runner_role(tmp_path: Path) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    addendum = build_oos_exposure_provenance_addendum(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        correction_at="2026-08-13T06:30:00Z",
    )
    assert addendum["original_runner_available"] is False
    assert addendum["runner_ref_role"] == "CURRENT_REMEDIATION_RECONSTRUCTION_ONLY"
    assert addendum["formal_oos_eligible"] is False
    first = write_oos_exposure_provenance_addendum_create_only(
        workspace_root=tmp_path,
        payload=addendum,
    )
    second = write_oos_exposure_provenance_addendum_create_only(
        workspace_root=tmp_path,
        payload=addendum,
    )
    assert first["status"] == "CREATED_PROVENANCE_CORRECTION"
    assert second["status"] == "IDEMPOTENT_EXACT"
    assert load_and_validate_oos_exposure_provenance_addendum(
        tmp_path,
        REPORT_ID,
    ) == addendum


def test_provenance_addendum_cli_is_create_only_and_idempotent(
    tmp_path: Path,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    command = [
        sys.executable,
        str(
            REPO_ROOT
            / "scripts/record_factorforge_oos_exposure_provenance_addendum.py"
        ),
        "--workspace-root",
        str(tmp_path),
        "--report-id",
        REPORT_ID,
        "--correction-at",
        "2026-08-13T06:30:00Z",
    ]

    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "CREATED_PROVENANCE_CORRECTION"
    assert first_payload["addendum"]["formal_oos_eligible"] is False
    assert Path(first_payload["path"]).is_file()

    repeated = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["status"] == "IDEMPOTENT_EXACT"


def test_provenance_addendum_rejects_incident_or_addendum_tamper(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=payload,
    )
    addendum = build_oos_exposure_provenance_addendum(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        correction_at="2026-08-13T06:30:00Z",
    )
    write_oos_exposure_provenance_addendum_create_only(
        workspace_root=tmp_path,
        payload=addendum,
    )
    marker = oos_exposure_incident_path(tmp_path, REPORT_ID)
    marker.write_text(marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="incident_binding"):
        load_and_validate_oos_exposure_provenance_addendum(tmp_path, REPORT_ID)

    marker.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    changed = dict(addendum)
    changed["original_runner_available"] = True
    with pytest.raises(ValueError, match="provenance_addendum"):
        write_oos_exposure_provenance_addendum_create_only(
            workspace_root=tmp_path,
            payload=changed,
        )


def test_host_private_registry_survives_public_marker_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    trust_root = tmp_path.parent / f"{tmp_path.name}_incident_trust"
    result = register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    assert result["status"] == "REGISTERED_PRIVATE_INCIDENT"
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(
        OOS_EXPOSURE_INSTALLATION_ID_ENV,
        "incident-test-installation",
    )
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [
        f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_incident"
    ]
    assert validate_oos_release_authorization(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        oos_window="2022-09-02/2025-07-11",
        sealed_token_sha256=TOKEN,
    ) == [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_incident"]


def test_existing_incident_host_private_registration_cli_is_idempotent(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_oos_exposure_incident_create_only(
        workspace_root=workspace,
        payload=_payload(workspace),
    )
    trust_root = tmp_path / "host-private-trust"
    command = [
        sys.executable,
        str(
            REPO_ROOT
            / "scripts/register_factorforge_oos_exposure_incident_host_private.py"
        ),
        "--workspace-root",
        str(workspace),
        "--report-id",
        REPORT_ID,
        "--trust-root",
        str(trust_root),
        "--installation-id",
        "incident-cli-installation",
    ]

    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "REGISTERED_PRIVATE_INCIDENT"
    assert first_payload["event"]["formal_oos_eligible"] is False

    repeated = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["status"] == (
        "IDEMPOTENT_PRIVATE_INCIDENT"
    )


@pytest.mark.parametrize(
    ("script_name", "required_terms"),
    [
        (
            "record_factorforge_oos_exposure_provenance_addendum.py",
            ("never restores formal-oos authority", "--correction-at"),
        ),
        (
            "register_factorforge_oos_exposure_incident_host_private.py",
            ("append-only negative state", "--trust-root"),
        ),
    ],
)
def test_oos_incident_remediation_cli_help_states_negative_authority(
    script_name: str,
    required_terms: tuple[str, ...],
) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    help_text = " ".join(completed.stdout.lower().split())
    assert all(term in help_text for term in required_terms)


def test_direct_allocator_replays_explicit_private_registry_without_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    trust_root = tmp_path.parent / f"{tmp_path.name}_incident_trust"
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    monkeypatch.delenv(OOS_EXPOSURE_TRUST_ROOT_ENV, raising=False)
    monkeypatch.delenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, raising=False)
    monkeypatch.delenv("FACTORFORGE_OOS_HOST_TRUST_ROOT", raising=False)
    monkeypatch.delenv("FACTORFORGE_OOS_HOST_INSTALLATION_ID", raising=False)

    with pytest.raises(ValueError, match="private_registry_incident"):
        _allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_test_001",
            report_id=REPORT_ID,
            parent_report_id="PARENT_REPORT_001",
            dataset_snapshot_sha256="b" * 64,
            oos_start="2026-01-01",
            oos_end="2026-03-31",
            sealed_token_sha256="c" * 64,
            allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
            expected_registry_sha256=None,
            trust_root=trust_root,
            installation_id="incident-test-installation",
        )


def test_explicit_private_incident_blocks_prereg_and_console_prepare_before_authoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "worktree"
    workspace = tree / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    payload = _payload(workspace)
    write_oos_exposure_incident_create_only(
        workspace_root=workspace,
        payload=payload,
    )
    trust_root = tmp_path / "host-state/research-org-trust"
    register_oos_exposure_incident_host_private(
        workspace_root=workspace,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(workspace, REPORT_ID).unlink()
    for name in (
        OOS_EXPOSURE_TRUST_ROOT_ENV,
        OOS_EXPOSURE_INSTALLATION_ID_ENV,
        "FACTORFORGE_OOS_HOST_TRUST_ROOT",
        "FACTORFORGE_OOS_HOST_INSTALLATION_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(
        child_preregistration.EvoChildPreregistrationError,
        match="private_registry_incident",
    ):
        child_preregistration.validate_evo_child_preregistration_inputs(
            workspace_root=workspace,
            parent_report_id="PARENT_REPORT_001",
            child_report_id=REPORT_ID,
            research_state={},
            research_conjecture={},
            approach_registry={},
            base_search_trial_ledger={},
            metric_verifier_spec={},
            threshold_registration={},
            agent_authored_child_web_research_plan={},
            expected_host_trust_manifest_sha256="b" * 64,
            incident_trust_root=trust_root,
            incident_installation_id="incident-test-installation",
        )

    class NeverRun:
        def run(self, *_args: object, **_kwargs: object) -> object:
            pytest.fail("authoring runner executed after private incident")

    with pytest.raises(child_runtime.EvoChildRuntimeError, match="private_registry_incident"):
        child_runtime.prepare_evo_child_execution(
            runner=NeverRun(),
            state_root=trust_root.parent,
            trust_root=trust_root,
            admissions_root=None,
            installation_id="incident-test-installation",
            job_id="job_incident_001",
            workspace_root=workspace,
            worktree=tree,
            parent_report_id="PARENT_REPORT_001",
            child_report_id=REPORT_ID,
            expected_host_trust_manifest_sha256=(
                ensure_runtime_trust_store(
                    trust_root,
                    installation_id="incident-test-installation",
                ).public_manifest["manifest_sha256"]
            ),
            trusted_parent_checkpoint={"ultimate_proof_sha256": "c" * 64},
            child_materializer_script=tree / "never-open-materializer.py",
            ultimate_script=tree / "never-open-ultimate.py",
            engine_root=tree,
            container_runtime=tree / "never-open-container",
            container_image_digest="sha256:" + "d" * 64,
            container_memory="512m",
            container_cpus="1",
            container_pids=64,
            container_tmpfs="size=64m",
            research_base_commit="e" * 40,
            execution_engine_commit="f" * 40,
            catalog_snapshot_path=tree / "never-open-catalog.json",
            catalog_projection_path=tree / "never-open-catalog-projection.json",
            calendar_snapshot_path=tree / "never-open-calendar.csv",
            calendar_projection_path=tree / "never-open-calendar-projection.json",
        )
    assert not child_preregistration.child_preregistration_receipt_path(
        workspace, REPORT_ID
    ).exists()
    assert list(trust_root.parent.rglob("stage__*.json")) == []


@pytest.mark.parametrize("stage_index", range(1, 8))
def test_each_runtime_stage_signer_blocks_private_incident(
    tmp_path: Path,
    stage_index: int,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = _payload(workspace)
    write_oos_exposure_incident_create_only(
        workspace_root=workspace,
        payload=payload,
    )
    trust_root = tmp_path / "host-trust"
    register_oos_exposure_incident_host_private(
        workspace_root=workspace,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-stage-test",
    )
    oos_exposure_incident_path(workspace, REPORT_ID).unlink()
    store = ensure_runtime_trust_store(
        trust_root,
        installation_id="incident-stage-test",
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    with pytest.raises(child_runtime.EvoChildRuntimeError, match="private_registry_incident"):
        child_runtime._record_stage(
            root=runtime_root,
            store=store,
            index=stage_index,
            stage=child_runtime._STAGES[stage_index - 1],
            identity={
                "job_id": "job_stage_test",
                "parent_report_id": "PARENT_REPORT_001",
                "child_report_id": REPORT_ID,
                "expected_host_trust_manifest_sha256": "a" * 64,
            },
            parent_checkpoint={"ultimate_proof_sha256": "b" * 64},
            previous_receipt_id=None,
            artifacts={},
            incident_workspace=workspace,
            incident_trust_root=trust_root,
            incident_installation_id="incident-stage-test",
            incident_report_id=REPORT_ID,
        )
    assert not child_runtime._stage_path(
        runtime_root,
        stage_index,
        child_runtime._STAGES[stage_index - 1],
    ).exists()


def test_stage_signer_and_incident_writer_have_deterministic_lock_order(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = _payload(workspace)
    trust_root = tmp_path / "host-trust"
    real_store = ensure_runtime_trust_store(
        trust_root,
        installation_id="incident-race-test",
    )
    writer_started = threading.Event()
    writer_finished = threading.Event()

    def writer() -> None:
        writer_started.set()
        prepare_oos_exposure_incident_host_private(
            workspace_root=workspace,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-race-test",
        )
        writer_finished.set()

    class StartWriterWhileSignerHoldsGuard:
        def sign(self, issuer: str, core: dict) -> dict:
            thread = threading.Thread(target=writer)
            thread.start()
            assert writer_started.wait(2)
            assert not writer_finished.wait(0.1)
            self.thread = thread
            return real_store.sign(issuer, core)

        def verify(self, *args, **kwargs):
            return real_store.verify(*args, **kwargs)

    wrapped = StartWriterWhileSignerHoldsGuard()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    first = child_runtime._record_stage(
        root=runtime_root,
        store=wrapped,
        index=1,
        stage=child_runtime._STAGES[0],
        identity={"child_report_id": REPORT_ID},
        parent_checkpoint={},
        previous_receipt_id=None,
        artifacts={},
        incident_workspace=workspace,
        incident_trust_root=trust_root,
        incident_installation_id="incident-race-test",
        incident_report_id=REPORT_ID,
    )
    wrapped.thread.join(2)
    assert first["path"].is_file()
    assert writer_finished.is_set()
    with pytest.raises(child_runtime.EvoChildRuntimeError, match="private_registry_incident"):
        child_runtime._record_stage(
            root=runtime_root,
            store=real_store,
            index=2,
            stage=child_runtime._STAGES[1],
            identity={"child_report_id": REPORT_ID},
            parent_checkpoint={},
            previous_receipt_id=first["receipt"]["receipt_id"],
            artifacts={},
            incident_workspace=workspace,
            incident_trust_root=trust_root,
            incident_installation_id="incident-race-test",
            incident_report_id=REPORT_ID,
        )


def test_incident_writer_wins_lock_before_stage_signer_no_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import factor_factory.oos_exposure_incident as incident_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = _payload(workspace)
    trust_root = tmp_path / "host-trust"
    real_append = incident_module._append_private_incident_event
    writer_has_lock = threading.Event()
    release_writer = threading.Event()

    def paused_append(**kwargs):
        writer_has_lock.set()
        assert release_writer.wait(2)
        return real_append(**kwargs)

    monkeypatch.setattr(incident_module, "_append_private_incident_event", paused_append)
    writer = threading.Thread(
        target=lambda: prepare_oos_exposure_incident_host_private(
            workspace_root=workspace,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-race-test",
        )
    )
    writer.start()
    assert writer_has_lock.wait(2)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    store = ensure_runtime_trust_store(
        trust_root,
        installation_id="incident-race-test",
    )
    outcome: list[BaseException | None] = []

    def signer() -> None:
        try:
            child_runtime._record_stage(
                root=runtime_root,
                store=store,
                index=1,
                stage=child_runtime._STAGES[0],
                identity={"child_report_id": REPORT_ID},
                parent_checkpoint={},
                previous_receipt_id=None,
                artifacts={},
                incident_workspace=workspace,
                incident_trust_root=trust_root,
                incident_installation_id="incident-race-test",
                incident_report_id=REPORT_ID,
            )
        except BaseException as exc:
            outcome.append(exc)
        else:
            outcome.append(None)

    signer_thread = threading.Thread(target=signer)
    signer_thread.start()
    assert signer_thread.is_alive()
    release_writer.set()
    writer.join(2)
    signer_thread.join(2)
    assert len(outcome) == 1
    assert isinstance(outcome[0], child_runtime.EvoChildRuntimeError)
    assert "private_registry_incident" in str(outcome[0])
    assert not child_runtime._stage_path(
        runtime_root, 1, child_runtime._STAGES[0]
    ).exists()


def test_launch_guard_releases_only_after_popen_linearization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = _payload(workspace)
    trust_root = tmp_path / "host-trust"
    ensure_runtime_trust_store(
        trust_root,
        installation_id="incident-launch-test",
    )
    writer_finished = threading.Event()
    writer_thread: list[threading.Thread] = []

    def writer() -> None:
        prepare_oos_exposure_incident_host_private(
            workspace_root=workspace,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-launch-test",
        )
        writer_finished.set()

    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, *_args, **_kwargs):
            thread = threading.Thread(target=writer)
            writer_thread.append(thread)
            thread.start()
            assert not writer_finished.wait(0.1)

        def communicate(self, timeout=None):
            assert writer_finished.wait(2)
            return "", ""

    @contextmanager
    def launch_guard():
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id="incident-launch-test",
        ):
            assert oos_exposure_incident_block_reasons(
                workspace,
                REPORT_ID,
                trust_root=trust_root,
                installation_id="incident-launch-test",
            ) == []
            yield

    monkeypatch.setattr(child_runtime.subprocess, "Popen", FakeProcess)
    completed = child_runtime._run_owned_process_group(
        ["never-executed"],
        cwd=workspace,
        env={},
        timeout_seconds=1,
        launch_guard=launch_guard(),
    )
    writer_thread[0].join(2)
    assert completed.returncode == 0
    assert writer_finished.is_set()
    assert oos_exposure_incident_block_reasons(
        workspace,
        REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-launch-test",
    ) == [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_incident"]
    execution_receipt = tmp_path / "runtime/execution__0001.json"
    execution_receipt.parent.mkdir()
    with pytest.raises(child_runtime.EvoChildRuntimeError, match="private_registry_incident"):
        child_runtime._sign_runtime_receipt_under_incident_guard(
            workspace=workspace,
            trust=trust_root,
            installation_id="incident-launch-test",
            report_id=REPORT_ID,
            store=ensure_runtime_trust_store(
                trust_root,
                installation_id="incident-launch-test",
            ),
            path=execution_receipt,
            core={
                "receipt_type": "EVO_CHILD_ULTIMATE_EXECUTION",
                "content_sha256": "a" * 64,
            },
        )
    assert not execution_receipt.exists()


@pytest.mark.parametrize("registry_attack", ["deleted", "tampered"])
def test_deleted_or_tampered_private_registry_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_attack: str,
) -> None:
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
    )
    trust_root = tmp_path.parent / f"{tmp_path.name}_incident_trust"
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    registry = oos_exposure_private_registry_path(trust_root)
    if registry_attack == "deleted":
        registry.unlink()
    else:
        registry.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(
        OOS_EXPOSURE_INSTALLATION_ID_ENV,
        "incident-test-installation",
    )
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [
        f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_invalid"
    ]


def test_signed_old_prefix_registry_and_head_replay_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_incident_trust"
    first = _payload(tmp_path)
    write_oos_exposure_incident_create_only(workspace_root=tmp_path, payload=first)
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    registry = oos_exposure_private_registry_path(trust_root)
    anchor = registry.with_name("registry.anchor.json")
    old_registry = registry.read_bytes()
    old_anchor = anchor.read_bytes()

    second_report = "SECOND_INCIDENT_REPORT"
    second = build_oos_exposure_incident(
        workspace_root=tmp_path,
        report_id=second_report,
        factor_id=FACTOR_ID,
        frozen_oos_start="2022-09-02",
        frozen_oos_end="2025-07-11",
        frozen_oos_release_token_sha256=TOKEN,
        exposed_overlap_start="2025-01-02",
        exposed_overlap_end="2025-07-11",
        exposed_row_count=676_659,
        exposed_period_count=126,
        source_path=tmp_path / "evidence/daily.csv",
        panel_path=tmp_path / "evidence/panel.parquet",
        metrics_path=tmp_path / "evidence/metrics.json",
        runner_path=tmp_path / "evidence/runner.py",
        incident_at="2026-08-13T07:00:00Z",
    )
    write_oos_exposure_incident_create_only(workspace_root=tmp_path, payload=second)
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=second_report,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )

    # Both restored files are authentic old signed state.  The immutable head
    # witness for sequence 2 remains and must make this rollback fail closed.
    registry.write_bytes(old_registry)
    anchor.write_bytes(old_anchor)
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, "incident-test-installation")
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [
        f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_invalid"
    ]


def test_deep_allocation_ancestor_incident_blocks_new_descendant(
    tmp_path: Path,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_allocation_trust"
    trust_root.mkdir(mode=0o700)
    ensure_runtime_trust_store(
        trust_root,
        installation_id="incident-test-installation",
    )

    def allocate(
        report: str,
        parent: str,
        allocation: str,
        token: str,
        start: str,
        end: str,
    ) -> None:
        _allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id=allocation,
            report_id=report,
            parent_report_id=parent,
            dataset_snapshot_sha256="b" * 64,
            oos_start=start,
            oos_end=end,
            sealed_token_sha256=token,
            allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
            expected_registry_sha256=(
                None
                if not (tmp_path / "objects/research_protocol/evo_oos_allocation_registry.json").exists()
                else __import__("hashlib").sha256(
                    (tmp_path / "objects/research_protocol/evo_oos_allocation_registry.json").read_bytes()
                ).hexdigest()
            ),
            trust_root=trust_root,
            installation_id="incident-test-installation",
        )

    allocate("ANCESTOR_CHILD_A", "ANCESTOR_ROOT", "allocation_ancestor_a", "1" * 64, "2026-01-01", "2026-03-31")
    allocate("ANCESTOR_CHILD_B", "ANCESTOR_CHILD_A", "allocation_ancestor_b", "2" * 64, "2026-04-01", "2026-06-30")
    root_incident = build_oos_exposure_incident(
        workspace_root=tmp_path,
        report_id="ANCESTOR_ROOT",
        factor_id=FACTOR_ID,
        frozen_oos_start="2022-09-02",
        frozen_oos_end="2025-07-11",
        frozen_oos_release_token_sha256=TOKEN,
        exposed_overlap_start="2025-01-02",
        exposed_overlap_end="2025-07-11",
        exposed_row_count=676_659,
        exposed_period_count=126,
        source_path=_artifact(tmp_path, "deep-source", "source"),
        panel_path=_artifact(tmp_path, "deep-panel", "panel"),
        metrics_path=_artifact(tmp_path, "deep-metrics", "metrics"),
        runner_path=_artifact(tmp_path, "deep-runner", "runner"),
        incident_at="2026-08-13T07:10:00Z",
    )
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=root_incident,
    )
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id="ANCESTOR_ROOT",
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, "ANCESTOR_ROOT").unlink()

    with pytest.raises(ValueError, match="private_registry_incident"):
        allocate(
            "ANCESTOR_CHILD_C",
            "ANCESTOR_CHILD_B",
            "allocation_ancestor_c",
            "3" * 64,
            "2026-07-01",
            "2026-09-30",
        )


def test_registry_and_anchor_deleted_with_heads_remaining_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_double_delete_trust"
    record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    registry = oos_exposure_private_registry_path(trust_root)
    registry.unlink()
    registry.with_name("registry.anchor.json").unlink()
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, "incident-test-installation")
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [
        f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_invalid"
    ]


def test_registry_and_anchor_deleted_with_heads_blocks_via_standard_host_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_standard_env_double_delete_trust"
    record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    registry = oos_exposure_private_registry_path(trust_root)
    registry.unlink()
    registry.with_name("registry.anchor.json").unlink()
    monkeypatch.delenv(OOS_EXPOSURE_TRUST_ROOT_ENV, raising=False)
    monkeypatch.delenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, raising=False)
    monkeypatch.setenv("FACTORFORGE_OOS_HOST_TRUST_ROOT", str(trust_root))
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_INSTALLATION_ID",
        "incident-test-installation",
    )
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID) == [
        f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_invalid"
    ]


@pytest.mark.parametrize("crash_boundary", ["after_prepared", "after_public"])
def test_durable_record_recovers_exactly_across_public_crash_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_boundary: str,
) -> None:
    import factor_factory.oos_exposure_incident as incident_module

    trust_root = tmp_path.parent / f"{tmp_path.name}_{crash_boundary}_trust"
    payload = _payload(tmp_path)
    if crash_boundary == "after_prepared":
        prepare_oos_exposure_incident_host_private(
            workspace_root=tmp_path,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-test-installation",
        )
        assert not oos_exposure_incident_path(tmp_path, REPORT_ID).exists()
    else:
        prepare_oos_exposure_incident_host_private(
            workspace_root=tmp_path,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-test-installation",
        )
        write_oos_exposure_incident_create_only(
            workspace_root=tmp_path,
            payload=payload,
        )
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, "incident-test-installation")
    assert oos_exposure_incident_block_reasons(tmp_path, REPORT_ID)
    result = incident_module.record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=payload,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    assert result["status"] in {"COMMITTED", "IDEMPOTENT_COMMITTED"}
    replay = incident_module.record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=payload,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    assert replay["status"] == "IDEMPOTENT_COMMITTED"


@pytest.mark.parametrize("boundary", ["journal", "head", "registry", "anchor"])
def test_private_transaction_rolls_forward_from_each_persisted_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    import factor_factory.oos_exposure_incident as incident_module

    trust_root = tmp_path.parent / f"{tmp_path.name}_{boundary}_transaction_trust"
    payload = _payload(tmp_path)
    ensure_empty_oos_exposure_private_registry(
        trust_root,
        installation_id="incident-test-installation",
    )
    original_recover = incident_module._recover_private_registry_transaction

    def crash_recover(root: Path, *, installation_id: str) -> bool:
        journal = incident_module._private_registry_journal_path(root)
        if not journal.exists():
            return original_recover(root, installation_id=installation_id)
        transaction = json.loads(journal.read_text(encoding="utf-8"))
        next_registry = transaction["next_registry"]
        next_head = transaction["next_head"]
        if boundary in {"head", "registry", "anchor"}:
            incident_module._write_private_head_once(root, next_head)
        if boundary in {"registry", "anchor"}:
            incident_module._atomic_replace_bytes(
                incident_module.oos_exposure_private_registry_path(root),
                incident_module._pretty_json_bytes(next_registry),
            )
        if boundary == "anchor":
            incident_module._atomic_replace_bytes(
                incident_module._private_registry_anchor_path(root),
                incident_module._pretty_json_bytes(next_head),
            )
        raise RuntimeError(f"crash:{boundary}")

    monkeypatch.setattr(incident_module, "_recover_private_registry_transaction", crash_recover)
    with pytest.raises(RuntimeError, match=f"crash:{boundary}"):
        prepare_oos_exposure_incident_host_private(
            workspace_root=tmp_path,
            payload=payload,
            trust_root=trust_root,
            installation_id="incident-test-installation",
        )
    monkeypatch.setattr(
        incident_module,
        "_recover_private_registry_transaction",
        original_recover,
    )
    recovered = ensure_empty_oos_exposure_private_registry(
        trust_root,
        installation_id="incident-test-installation",
    )
    assert any(event.get("report_id") == REPORT_ID for event in recovered["events"])


def test_post_allocation_ancestor_incident_blocks_every_formal_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_post_ancestor_trust"
    trust_root.mkdir(mode=0o700)
    ensure_runtime_trust_store(trust_root, installation_id="incident-test-installation")
    _allocate_fresh_child_oos(
        workspace_root=tmp_path,
        allocation_id="allocation_descendant_001",
        report_id="DESCENDANT_REPORT",
        parent_report_id=REPORT_ID,
        dataset_snapshot_sha256="b" * 64,
        oos_start="2026-01-01",
        oos_end="2026-03-31",
        sealed_token_sha256="c" * 64,
        allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
        expected_registry_sha256=None,
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
        trust_root=trust_root,
        installation_id="incident-test-installation",
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    monkeypatch.setenv(OOS_EXPOSURE_TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(OOS_EXPOSURE_INSTALLATION_ID_ENV, "incident-test-installation")
    expected = f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_incident"
    assert validate_oos_release_authorization(
        workspace_root=tmp_path,
        report_id="DESCENDANT_REPORT",
        oos_window="2026-01-01/2026-03-31",
        sealed_token_sha256="c" * 64,
    ) == [expected]
    assert validate_oos_release_preflight(
        workspace_root=tmp_path,
        report_id="DESCENDANT_REPORT",
        release_manifest_payload={},
    ) == [expected]
    assert validate_child_oos_finalizer_authority(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id="DESCENDANT_REPORT",
        allocation_id="allocation_descendant_001",
    ) == [expected]
    assert validate_oos_release_consumption(
        workspace_root=tmp_path,
        report_id="DESCENDANT_REPORT",
        release_manifest_path=tmp_path / "release.json",
    ) == [expected]
    with pytest.raises(ValueError, match="private_registry_incident"):
        consume_oos_allocation_for_release(
            workspace_root=tmp_path,
            report_id="DESCENDANT_REPORT",
            release_manifest_path=tmp_path / "release.json",
        )
    with pytest.raises(ValueError, match="private_registry_incident"):
        validate_web_factor_proof_preregistration(
            tmp_path,
            {
                "identity": {
                    "report_id": "DESCENDANT_REPORT",
                    "factor_id": FACTOR_ID,
                    "research_id": "research_descendant_001",
                }
            },
        )


def test_deleted_allocation_registry_cannot_reset_deep_lineage_root(
    tmp_path: Path,
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}_deleted_lineage_trust"
    installation_id = "deleted-lineage-test"
    ensure_runtime_trust_store(trust_root, installation_id=installation_id)
    child_report_id = "DESCENDANT_REPORT"
    grandchild_report_id = "DEEP_DESCENDANT_REPORT"

    _allocate_fresh_child_oos(
        workspace_root=tmp_path,
        allocation_id="allocation_descendant_001",
        report_id=child_report_id,
        parent_report_id=REPORT_ID,
        dataset_snapshot_sha256="b" * 64,
        oos_start="2026-01-01",
        oos_end="2026-03-31",
        sealed_token_sha256="c" * 64,
        allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
        expected_registry_sha256=None,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    assert oos_allocation_path(tmp_path, child_report_id).is_file()
    assert oos_allocation_receipt_path(tmp_path, child_report_id).is_file()

    record_oos_exposure_incident_durable(
        workspace_root=tmp_path,
        payload=_payload(tmp_path),
        trust_root=trust_root,
        installation_id=installation_id,
    )
    oos_exposure_incident_path(tmp_path, REPORT_ID).unlink()
    oos_registry_path(tmp_path).unlink()

    with pytest.raises(ValueError, match="incident_lineage_registry_missing"):
        _allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_deep_descendant_001",
            report_id=grandchild_report_id,
            parent_report_id=child_report_id,
            dataset_snapshot_sha256="d" * 64,
            oos_start="2026-04-01",
            oos_end="2026-06-30",
            sealed_token_sha256="e" * 64,
            allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_LEGACY_TEST,
            expected_registry_sha256=None,
            trust_root=trust_root,
            installation_id=installation_id,
        )
    assert not oos_allocation_path(tmp_path, grandchild_report_id).exists()
    assert not oos_allocation_receipt_path(tmp_path, grandchild_report_id).exists()

    reasons = validate_oos_release_authorization(
        workspace_root=tmp_path,
        report_id=child_report_id,
        oos_window="2026-01-01/2026-03-31",
        sealed_token_sha256="c" * 64,
        incident_trust_root=trust_root,
        incident_installation_id=installation_id,
    )
    assert any("incident_lineage_registry_missing" in reason for reason in reasons)
