from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from factor_factory.evo_child_materialization_admission import (
    child_materialization_admission_path,
    materialize_evo_child_materialization_admission,
    validate_evo_child_materialization_admission,
)
from factor_factory.evo_child_materialization_ticket import (
    materialize_public_child_materialization_ticket,
)
from tests.test_factorforge_pre_oos_human_bridge import (
    CHILD_ID,
    INSTALLATION_ID,
    REPORT_ID,
    _admissions_root,
    _approved_ready,
    _host_manifest_pin,
    _host_trust_root,
)


def _materialized_fixture(tmp_path, monkeypatch):
    import pandas as pd

    import tests.test_factorforge_pre_oos_human_bridge as bridge_fixtures

    original_daily_authority = bridge_fixtures._write_parent_daily_authority

    def formal_daily_authority(root):
        original_daily_authority(root)
        frozen = root / "runs" / REPORT_ID / "frozen_inputs"
        dates = ["2020-01-02", "2021-01-04", "2022-01-04"]
        frame = pd.DataFrame(
            {
                "trade_date": dates,
                "ts_code": ["000001.SZ"] * len(dates),
                "open": [10.0, 11.0, 12.0],
                "close": [10.5, 11.5, 12.5],
                "pre_close": [9.9, 10.9, 11.9],
                "volume": [100.0, 110.0, 120.0],
            }
        )
        frame.to_csv(frozen / "daily.csv", index=False)
        frame.to_parquet(frozen / "evaluation_daily.parquet", index=False)
        frame.to_parquet(frozen / "signal_daily.parquet", index=False)

    monkeypatch.setattr(
        bridge_fixtures, "_write_parent_daily_authority", formal_daily_authority
    )
    _approved_ready(tmp_path)
    pin = _host_manifest_pin(tmp_path)
    from tests.test_factorforge_pre_oos_human_bridge import (
        _materialize_ready_child_preregistration,
    )

    prereg = _materialize_ready_child_preregistration(tmp_path)
    assert prereg["verdict"] == "PASS"
    ready = materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        materialization_ready=True,
    )
    assert ready["status"] == "MATERIALIZATION_READY"

    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                root
                / "skills"
                / "factor-forge-step6"
                / "scripts"
                / "materialize_step6_child_revision.py"
            ),
            "--factorforge-root",
            str(tmp_path),
            "--parent-report-id",
            REPORT_ID,
            "--child-report-id",
            CHILD_ID,
            "--expected-host-trust-manifest-sha256",
            pin,
            "--incident-trust-root",
            str(_host_trust_root(tmp_path)),
            "--incident-installation-id",
            INSTALLATION_ID,
        ],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    from factor_factory.evo_child_materialization_admission import (
        child_materialization_report_path,
    )

    report_path = child_materialization_report_path(tmp_path, REPORT_ID, CHILD_ID)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    target_paths = [
        tmp_path / row["path"] for row in report["materialization_target_hashes"]
    ]
    return pin, report_path, target_paths


def test_host_materialization_admission_binds_exact_readback(tmp_path, monkeypatch):
    pin, _report, _targets = _materialized_fixture(tmp_path, monkeypatch)
    result = materialize_evo_child_materialization_admission(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        expected_host_trust_manifest_sha256=pin,
    )
    assert result["verdict"] == "PASS"
    payload, reasons = validate_evo_child_materialization_admission(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=pin,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert reasons == []
    assert payload is not None
    assert payload["authority"]["child_execution_start_step"] == "3b"

    missing_context, missing_reasons = validate_evo_child_materialization_admission(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=pin,
    )
    assert missing_context is None
    assert any("incident_host_context_required" in reason for reason in missing_reasons)


def test_target_tamper_invalidates_host_materialization_admission(tmp_path, monkeypatch):
    pin, _report, target_paths = _materialized_fixture(tmp_path, monkeypatch)
    materialize_evo_child_materialization_admission(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        expected_host_trust_manifest_sha256=pin,
    )
    target_paths[0].write_text("tampered\n", encoding="utf-8")
    payload, reasons = validate_evo_child_materialization_admission(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=pin,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert payload is None
    assert any("hash_mismatch" in reason for reason in reasons)
    assert child_materialization_admission_path(tmp_path, CHILD_ID).is_file()
