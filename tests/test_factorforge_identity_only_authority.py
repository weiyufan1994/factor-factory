from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import build_factorforge_component_obligation_report as component_cli
from scripts import build_factorforge_metric_verifier_reports as metric_cli


@pytest.mark.parametrize(
    ("module", "identity_function_name"),
    (
        (metric_cli, "metric_verifier_identities"),
        (component_cli, "component_verifier_identities"),
    ),
)
def test_identity_only_cli_explicitly_denies_current_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    module: object,
    identity_function_name: str,
) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        identity_function_name,
        lambda **_kwargs: {"dataset_snapshot_hash": "a" * 64},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(getattr(module, "__file__")),
            "--workspace-root",
            str(tmp_path),
            "--panel",
            str(tmp_path / "panel.csv"),
            "--spec",
            str(spec_path),
            "--identity-only",
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current_formal_authority_verified"] is False
    assert payload["formal_proof_eligible"] is False
