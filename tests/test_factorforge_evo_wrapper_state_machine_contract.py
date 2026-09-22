from __future__ import annotations

import json
from pathlib import Path

import pytest

from factor_factory.research_evidence import sha256_file
from scripts import run_factorforge_ultimate as wrapper


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("current_state", ["TRANSFER_RECORDED", "COLD_START_RECORDED"])
def test_transfer_or_cold_stage_replays_historical_minimal_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    current_state: str,
) -> None:
    root = tmp_path / "workspace"
    report_id = "EVO_WRAPPER_STATE"
    lifecycle_path = root / "objects/evo_v2" / report_id / "lifecycle.json"
    snapshot_path = (
        root
        / "objects/evo_v2"
        / report_id
        / "lifecycle_history"
        / "lifecycle__0003.json"
    )
    manifest_path = root / "objects/evo_v2" / report_id / "staging_manifest.json"
    events = [
        {"sequence": 1, "to_state": "PREDICTIONS_FROZEN"},
        {"sequence": 2, "to_state": "QUALIFIED_CONTRADICTION"},
        {"sequence": 3, "to_state": "MINIMAL_MECHANISM_DELTA"},
        {"sequence": 4, "to_state": current_state},
    ]
    snapshot = {
        "current_state": "MINIMAL_MECHANISM_DELTA",
        "events": events[:3],
        "content_sha256": "a" * 64,
    }
    lifecycle = {
        "current_state": current_state,
        "events": events,
        "content_sha256": "b" * 64,
    }
    _write(snapshot_path, snapshot)
    _write(lifecycle_path, lifecycle)
    manifest = {
        "events": [
            {"stage": "ADMIT_FEEDBACK"},
            {
                "stage": "ADMIT_COUNCIL_OUTCOME",
                "outcome": "MINIMAL_MECHANISM_DELTA",
                "lifecycle_binding": {
                    "current_state": "MINIMAL_MECHANISM_DELTA",
                    "content_sha256": snapshot["content_sha256"],
                    "sha256": sha256_file(snapshot_path),
                },
            },
            {"stage": "ADMIT_TRANSFER"},
            {
                "stage": "RECORD_USE",
                "lifecycle_binding": {
                    "current_state": current_state,
                    "content_sha256": lifecycle["content_sha256"],
                    "sha256": sha256_file(lifecycle_path),
                },
            },
        ]
    }
    _write(manifest_path, manifest)

    monkeypatch.setattr(
        wrapper,
        "epistemic_evolution_lifecycle_path",
        lambda _root, _report: lifecycle_path,
    )
    monkeypatch.setattr(
        wrapper,
        "epistemic_evolution_lifecycle_snapshot_path",
        lambda _root, _report, generation: (
            snapshot_path if generation == 3 else root / "unexpected.json"
        ),
    )
    monkeypatch.setattr(
        wrapper,
        "evo_staging_manifest_path",
        lambda _root, _report: manifest_path,
    )
    monkeypatch.setattr(
        wrapper,
        "load_evo_json_object",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        wrapper,
        "validate_epistemic_evolution_lifecycle",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        wrapper,
        "validate_evo_v2_staging_manifest",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        wrapper,
        "pre_oos_outcome_evidence_reference",
        lambda **_kwargs: ({"status": "PASS"}, []),
    )

    valid, reasons, verifier = wrapper._validated_evo_outcome_stage(
        root,
        report_id,
        "MINIMAL_MECHANISM_DELTA",
        allowed_current_states={"TRANSFER_RECORDED", "COLD_START_RECORDED"},
        required_event_count=4,
    )

    assert valid is True
    assert reasons == []
    assert verifier == {"status": "PASS"}

    manifest["events"][1]["lifecycle_binding"] = manifest["events"][-1][
        "lifecycle_binding"
    ]
    _write(manifest_path, manifest)
    valid, reasons, _verifier = wrapper._validated_evo_outcome_stage(
        root,
        report_id,
        "MINIMAL_MECHANISM_DELTA",
        allowed_current_states={"TRANSFER_RECORDED", "COLD_START_RECORDED"},
        required_event_count=4,
    )
    assert valid is False
    assert "staging_lifecycle_outcome_mismatch" in reasons
