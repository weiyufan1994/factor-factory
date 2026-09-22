from __future__ import annotations

import json
from pathlib import Path

import pytest

from factor_factory.research_obligation_verifier import stable_hash
from scripts import record_factorforge_evo_v2_lifecycle as writer
from tests.test_factorforge_evo_v2 import REPORT_ID
from tests.test_factorforge_evo_v2_staging import _verifier_ref, _write_lifecycle


def _bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def test_signed_receipt_partial_write_is_not_published_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "lifecycle_transition_receipt__0003.json"
    payload = {"receipt_id": "receipt_001", "signature": {"value_b64": "x" * 256}}
    real_write = writer.os.write
    calls = 0

    def interrupted_write(descriptor: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, data[:17])
        raise OSError("simulated_receipt_interrupt")

    monkeypatch.setattr(writer.os, "write", interrupted_write)
    with pytest.raises(OSError, match="simulated_receipt_interrupt"):
        writer._write_immutable_json(path, payload, conflict="RECEIPT_CONFLICT")
    assert not path.exists()

    monkeypatch.setattr(writer.os, "write", real_write)
    writer._write_immutable_json(path, payload, conflict="RECEIPT_CONFLICT")
    assert path.read_bytes() == _bytes(payload)
    writer._write_immutable_json(path, payload, conflict="RECEIPT_CONFLICT")


def test_snapshot_publish_interrupt_cleans_linked_temp_on_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "lifecycle_history" / "lifecycle__0003.json"
    payload = {
        "report_id": "ATOMIC_LIFECYCLE",
        "current_state": "MINIMAL_MECHANISM_DELTA",
        "events": [{"sequence": 3}],
    }
    real_fsync_directory = writer._fsync_directory
    interrupted = False

    def interrupt_after_publish(_path: Path) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise OSError("simulated_snapshot_dir_fsync_interrupt")
        real_fsync_directory(_path)

    monkeypatch.setattr(writer, "_fsync_directory", interrupt_after_publish)
    with pytest.raises(OSError, match="simulated_snapshot_dir_fsync_interrupt"):
        writer._write_immutable_json(path, payload)
    assert path.read_bytes() == _bytes(payload)

    monkeypatch.setattr(writer, "_fsync_directory", real_fsync_directory)
    writer._write_immutable_json(path, payload)
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_current_lifecycle_exact_replay_recovers_after_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "lifecycle.json"
    parent = {
        "report_id": "ATOMIC_LIFECYCLE",
        "current_state": "QUALIFIED_CONTRADICTION",
        "events": [{"sequence": 1}],
    }
    path.write_bytes(_bytes(parent))
    payload = {
        "report_id": "ATOMIC_LIFECYCLE",
        "current_state": "MINIMAL_MECHANISM_DELTA",
        "events": [{"sequence": 1}, {"sequence": 2}],
    }
    parent_sha = stable_hash(parent)
    real_fsync_directory = writer._fsync_directory

    def interrupt_after_replace(_path: Path) -> None:
        raise OSError("simulated_current_dir_fsync_interrupt")

    monkeypatch.setattr(writer, "_fsync_directory", interrupt_after_replace)
    with pytest.raises(OSError, match="simulated_current_dir_fsync_interrupt"):
        writer._write_once_or_cas(path, payload, parent_sha)
    assert json.loads(path.read_text(encoding="utf-8")) == payload

    monkeypatch.setattr(writer, "_fsync_directory", real_fsync_directory)
    writer._write_once_or_cas(path, payload, parent_sha)
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_host_cli_accepts_exact_transition_replay_with_original_parent_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent_sha, _current = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
        ],
    )
    reference = _verifier_ref(root)
    private_inside = root / "host-private-trust"
    private_outside = root.parent / "host-private-trust"
    private_inside.rename(private_outside)
    monkeypatch.setattr(
        writer.sys,
        "argv",
        [
            str(Path(writer.__file__)),
            "--workspace-root",
            str(root),
            "--report-id",
            REPORT_ID,
            "--to-state",
            "MINIMAL_MECHANISM_DELTA",
            "--evidence-ref",
            json.dumps(reference, sort_keys=True),
            "--expected-parent-sha256",
            parent_sha,
            "--trust-root",
            str(private_outside),
            "--installation-id",
            "evo-staging-test-installation-001",
        ],
    )
    assert writer.main() == 0
