from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import factor_factory.console.web_factor_proof as web_factor_proof
import factor_factory.evo_child_execution as child_execution
from factor_factory.evo_v2 import canonical_json_bytes, sha256_file, stable_json_hash


PARENT_REPORT_ID = "PARENT_EVO_EXECUTION"
CHILD_REPORT_ID = f"{PARENT_REPORT_ID}__EVO_CHILD_001"
HOST_TRUST_PIN = "a" * 64


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _ref(root: Path, path: Path, payload: dict | None = None) -> dict[str, str]:
    result = {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }
    if payload is not None and "content_sha256" in payload:
        result["content_sha256"] = str(payload["content_sha256"])
    return result


def _write_context(fixture: SimpleNamespace) -> None:
    fixture.context["artifacts"]["evo_transfer_diagnostic_panel"][
        "sha256"
    ] = sha256_file(fixture.panel_path)
    _write_json(fixture.context_path, fixture.context)


def _execution_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar_dates = [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
    ]
    signal_dates = calendar_dates[:3]
    label_dates = {
        "2024-01-01": ("2024-01-02", "2024-01-03"),
        "2024-01-02": ("2024-01-03", "2024-01-04"),
        "2024-01-03": ("2024-01-04", "2024-01-05"),
    }

    monkeypatch.setattr(
        web_factor_proof,
        "_trusted_calendar_snapshot",
        lambda **_kwargs: {"dates": calendar_dates},
    )

    def fake_window(_plan: dict, *, calendar_dates: list[str]):
        assert calendar_dates == [
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]
        return (
            {
                "is_start": signal_dates[0],
                "is_end": signal_dates[-1],
                "oos_start": "2024-02-01",
                "purge_days": 1,
                "embargo_days": 1,
            },
            signal_dates,
        )

    monkeypatch.setattr(web_factor_proof, "_evo_is_window_contract", fake_window)
    monkeypatch.setattr(
        web_factor_proof,
        "_expected_label_dates",
        lambda _calendar, _signals: label_dates,
    )

    plan = {"identity": {"report_id": PARENT_REPORT_ID}}
    plan_path = root / "identity" / "web_research_plan.json"
    _write_json(plan_path, plan)
    formula_test = {
        "test_id": "transfer_formula_001",
        "implementation_mode": "FORMULA_DIAGNOSTIC",
        "formula_or_law": "close",
        "signal_column": "transfer_signal",
        "required_evidence": [],
    }
    addendum = {
        "frozen_web_research_plan_ref": _ref(root, plan_path),
        "execution_tests": [formula_test],
    }

    codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    bases = {"000001.SZ": 10.0, "000002.SZ": 20.0, "000003.SZ": 40.0}
    increments = {"000001.SZ": 1.0, "000002.SZ": 3.0, "000003.SZ": -1.0}
    signal_rows: list[dict] = []
    for day_index, trade_date in enumerate(signal_dates):
        for code in codes:
            signal_rows.append(
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "close": bases[code] + increments[code] * day_index,
                }
            )
    signal_daily = pd.DataFrame(signal_rows)

    evaluation_rows: list[dict] = []
    for day_index, trade_date in enumerate(calendar_dates):
        for code in codes:
            evaluation_rows.append(
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "close": bases[code] + increments[code] * day_index,
                }
            )
    evaluation_daily = pd.DataFrame(evaluation_rows)
    price_lookup = {
        (row.ts_code, row.trade_date): float(row.close)
        for row in evaluation_daily.itertuples(index=False)
    }
    signal_lookup = {
        (row.ts_code, row.trade_date): float(row.close)
        for row in signal_daily.itertuples(index=False)
    }
    panel_rows: list[dict] = []
    for trade_date in signal_dates:
        start_date, end_date = label_dates[trade_date]
        for code in codes:
            start_price = price_lookup[(code, start_date)]
            end_price = price_lookup[(code, end_date)]
            panel_rows.append(
                {
                    "trade_date": trade_date,
                    "code": code,
                    "future_return_1d": end_price / start_price - 1.0,
                    "label_start_date": start_date,
                    "label_end_date": end_date,
                    "label_start_price": start_price,
                    "label_end_price": end_price,
                    "transfer_signal": signal_lookup[(code, trade_date)],
                }
            )
    panel = pd.DataFrame(panel_rows)

    frozen = root / "runs" / PARENT_REPORT_ID / "frozen_inputs"
    frozen.mkdir(parents=True)
    signal_path = frozen / "signal_daily.parquet"
    evaluation_path = frozen / "evaluation_daily.parquet"
    signal_daily.to_parquet(signal_path, index=False)
    evaluation_daily.to_parquet(evaluation_path, index=False)
    child_run = root / "runs" / CHILD_REPORT_ID
    child_run.mkdir(parents=True)
    panel_path = child_run / "step4_transfer_panel.parquet"
    panel.to_parquet(panel_path, index=False)
    context_path = child_run / f"shared_evaluation_context__{CHILD_REPORT_ID}.json"
    context = {
        "paths": {
            "evo_transfer_diagnostic_panel_parquet": panel_path.relative_to(
                root
            ).as_posix(),
        },
        "artifacts": {
            "evo_transfer_diagnostic_panel": {"sha256": sha256_file(panel_path)}
        },
        "signal_daily_input_path": signal_path.relative_to(root).as_posix(),
        "signal_daily_input_hash": sha256_file(signal_path),
        "evaluation_daily_input_path": evaluation_path.relative_to(root).as_posix(),
        "evaluation_daily_input_hash": sha256_file(evaluation_path),
    }
    _write_json(context_path, context)
    diagnostic_contract = {
        "frozen_daily_input_refs": {
            "signal_daily_df_parquet": _ref(root, signal_path),
            "evaluation_daily_df_parquet": _ref(root, evaluation_path),
        }
    }
    return SimpleNamespace(
        root=root,
        addendum=addendum,
        diagnostic_contract=diagnostic_contract,
        signal_daily=signal_daily,
        signal_path=signal_path,
        evaluation_daily=evaluation_daily,
        evaluation_path=evaluation_path,
        panel=panel,
        panel_path=panel_path,
        context=context,
        context_path=context_path,
    )


def _derive(fixture: SimpleNamespace):
    return child_execution._derive_purged_is_panel(
        root=fixture.root,
        parent_report_id=PARENT_REPORT_ID,
        child_report_id=CHILD_REPORT_ID,
        addendum=fixture.addendum,
        diagnostic_contract=fixture.diagnostic_contract,
    )


def test_signed_signal_snapshot_tamper_cannot_rebind_through_shared_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _execution_fixture(tmp_path, monkeypatch)
    _frame, coverage, _source = _derive(fixture)
    assert coverage["coverage_status"] == "COMPLETE"

    tampered = fixture.signal_daily.copy()
    tampered.loc[0, "close"] += 100.0
    tampered.to_parquet(fixture.signal_path, index=False)
    fixture.context["signal_daily_input_hash"] = sha256_file(fixture.signal_path)
    _write_json(fixture.context_path, fixture.context)

    with pytest.raises(
        child_execution.EvoChildExecutionError,
        match="frozen_signal_daily_input_binding",
    ):
        _derive(fixture)


def test_label_prices_cannot_be_forged_consistently_inside_step4_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _execution_fixture(tmp_path, monkeypatch)
    _derive(fixture)

    forged = fixture.panel.copy()
    forged.loc[0, "label_start_price"] *= 2.0
    forged.loc[0, "label_end_price"] *= 2.0
    forged.loc[0, "future_return_1d"] = (
        forged.loc[0, "label_end_price"] / forged.loc[0, "label_start_price"] - 1.0
    )
    forged.to_parquet(fixture.panel_path, index=False)
    _write_context(fixture)

    with pytest.raises(
        child_execution.EvoChildExecutionError,
        match="purged_is_raw_close_reconciliation",
    ):
        _derive(fixture)


def test_selective_row_panel_is_rejected_before_diagnostic_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _execution_fixture(tmp_path, monkeypatch)
    _derive(fixture)

    fixture.panel.iloc[:-1].to_parquet(fixture.panel_path, index=False)
    _write_context(fixture)

    with pytest.raises(
        child_execution.EvoChildExecutionError,
        match="purged_is_instrument_date_coverage",
    ):
        _derive(fixture)


def test_formula_diagnostic_rejects_all_null_signal_coverage(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date for date in ("2024-01-01", "2024-01-02", "2024-01-03") for _ in range(3)],
            "code": ["A", "B", "C"] * 3,
            "future_return_1d": [0.01, 0.02, 0.03] * 3,
            "transfer_signal": [np.nan] * 9,
        }
    )
    addendum = {
        "required_evidence_refs": {},
        "execution_tests": [
            {
                "test_id": "all_null_signal_001",
                "implementation_mode": "FORMULA_DIAGNOSTIC",
                "formula_or_law": "close",
                "signal_column": "transfer_signal",
                "required_evidence": [],
                "expected_signature": "non_null ranked signal",
                "falsifier": "no eligible observations",
            }
        ],
    }

    with pytest.raises(
        child_execution.EvoChildExecutionError,
        match="formula_insufficient_coverage:all_null_signal_001",
    ):
        child_execution._test_results(root=tmp_path, frame=frame, addendum=addendum)


def test_failed_evidence_predicate_is_executed_and_recorded_as_false(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    test_id = "predicate_failure_001"
    evidence_key = "objects/evidence/predicate_failure_001.json"
    predicate = {
        "contract_version": "factorforge_evo_panel_predicate_v1",
        "metric": "MEAN",
        "column": "transfer_signal",
        "comparator": "GT",
        "threshold": 10.0,
        "min_observations": 3,
    }
    bundle = child_execution.verifier_source_bundle()
    core = {
        "contract_version": "factorforge_evo_execution_evidence_obligation_v1",
        "test_id": test_id,
        "evidence_kind": "VERIFIER_CONTRACT",
        "artifact_contract": child_execution.EVO_CHILD_EXECUTION_RESULT_VERSION,
        "verifier_id": child_execution.EVO_CHILD_EXECUTION_VERIFIER_ID,
        "verifier_contract_version": (
            child_execution.EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION
        ),
        "verifier_source_bundle_sha256": bundle["source_bundle_sha256"],
        "input_role": "EVO_PURGED_IS_PANEL",
        "predicate": predicate,
        "information_set": "PURGED_IS_ONLY",
        "status": "PREREGISTERED_AND_BOUND_NOT_EVALUATED",
    }
    evidence = {**core, "content_sha256": stable_json_hash(core)}
    evidence_path = root / evidence_key
    _write_json(evidence_path, evidence)
    addendum = {
        "required_evidence_refs": {evidence_key: _ref(root, evidence_path, evidence)},
        "execution_tests": [
            {
                "test_id": test_id,
                "implementation_mode": "EVIDENCE_OBLIGATION",
                "formula_or_law": None,
                "signal_column": None,
                "required_evidence": [evidence_key],
                "expected_signature": "mean exceeds preregistered threshold",
                "falsifier": "mean does not exceed threshold",
            }
        ],
    }
    frame = pd.DataFrame(
        {
            "trade_date": ["2024-01-01"] * 3,
            "code": ["A", "B", "C"],
            "future_return_1d": [0.01, -0.01, 0.00],
            "transfer_signal": [1.0, 2.0, 3.0],
        }
    )

    results = child_execution._test_results(root=root, frame=frame, addendum=addendum)

    predicate_result = results[0]["observed_metrics"]["predicate_results"][0]
    assert predicate_result["observed_value"] == 2.0
    assert predicate_result["predicate_comparison_result"] is False
    assert results[0]["adjudication"] == (
        "HOST_REVIEW_REQUIRED_NOT_AUTOMATICALLY_INFERRED"
    )


def test_cold_branch_returns_non_execution_summary_without_writing_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(
        child_execution,
        "validate_evo_transfer_diagnostic_contract",
        lambda *_args, **_kwargs: [],
    )

    result = child_execution.materialize_evo_child_execution_result(
        workspace_root=root,
        parent_report_id=PARENT_REPORT_ID,
        child_report_id=CHILD_REPORT_ID,
        diagnostic_contract={"result_receipt_required": False},
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )

    assert result == {
        "verdict": "PASS",
        "status": "COLD_START_NO_TRANSFER_TESTS",
        "execution_completed": False,
        "factor_verdict": "NOT_ISSUED",
    }
    assert not child_execution.evo_child_execution_result_path(
        root, CHILD_REPORT_ID
    ).exists()
    assert not child_execution.evo_child_execution_panel_path(
        root, CHILD_REPORT_ID
    ).exists()


def test_deleted_downstream_contract_markers_cannot_downgrade_child_to_legacy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    intent_path = (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_intent__{CHILD_REPORT_ID}.json"
    )
    _write_json(
        intent_path,
        {
            "parent_report_id": PARENT_REPORT_ID,
            "child_report_id": CHILD_REPORT_ID,
        },
    )

    reasons = child_execution.validate_evo_child_execution_gate(
        workspace_root=root,
        report_id=CHILD_REPORT_ID,
        factor_run_master={},
        expected_host_trust_manifest_sha256=None,
    )

    assert reasons == [
        f"{child_execution.BLOCK_EVO_CHILD_EXECUTION}:"
        "downstream_canonical_contract_missing"
    ]
