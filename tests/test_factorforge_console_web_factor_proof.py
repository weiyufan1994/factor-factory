from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import factor_factory.console.web_factor_proof as web_factor_proof
from factor_factory.console.web_factor_proof import (
    _trusted_calendar_snapshot,
    finalize_web_factor_proof,
    prepare_web_factor_proof,
    validate_web_factor_proof_preregistration,
    web_factor_proof_paths,
)
from factor_factory.research_evidence import sha256_file


def _plan(calendar_dates: list[str]) -> tuple[dict, list[str]]:
    selected = [
        value
        for value in calendar_dates
        if "2024-01-01" <= value <= "2024-06-30"
    ][:82]
    return (
        {
            "identity": {
                "job_id": "job_proof12345",
                "report_id": "WEB_PROOF_TEST",
                "factor_id": "WEB_PROOF_FACTOR",
                "research_id": "web_proof_test",
            },
            "evidence_policy": {
                "is_start": "2020-01-01",
                "is_end": "2023-12-31",
                "oos_start": selected[0],
                "oos_end": selected[-1],
                "transaction_cost_bps": 30.0,
                "cost_model_id": "factorforge_step4_turnover_30bps_v1",
                "universe_id": "proof_test_universe",
                "investability_mask_id": "proof_test_mask",
                "trial_budget": 1,
            },
            "economic_mechanism": {"claim_class": "liquidity_rent"},
            "hypotheses": [
                {
                    "kind": "preferred",
                    "hypothesis_id": "H1",
                    "claim": "registered proof-chain test",
                }
            ],
            "research_object": {"formula_or_law": "close"},
            "data_plan": {"daily_fields": ["close"]},
        },
        selected,
    )


def _write_shared_panel(
    root: Path,
    selected: list[str],
    *,
    direction: float,
    bad_label_date: bool = False,
    include_source_hash: bool = True,
) -> None:
    rows = []
    for date_index, signal_date in enumerate(selected[:-2]):
        for asset_index in range(20):
            forward_return = (
                direction * (0.002 + 0.00012 * asset_index)
                + 0.00045 * math.sin(date_index * 0.41 + asset_index * 1.17)
            )
            label_start = selected[date_index + 1]
            if bad_label_date and date_index == 0 and asset_index == 0:
                label_start = selected[date_index + 2]
            rows.append(
                {
                    "datetime": pd.Timestamp(signal_date),
                    "trade_date": signal_date,
                    "code": f"{asset_index:06d}.SZ",
                    "factor_value": float(asset_index),
                    "future_return_1d": forward_return,
                    "label_start_date": label_start,
                    "label_end_date": selected[date_index + 2],
                    "label_start_price": 100.0,
                    "label_end_price": 100.0 * (1.0 + forward_return),
                }
            )
    run_root = root / "runs" / "WEB_PROOF_TEST"
    run_root.mkdir(parents=True)
    panel_path = run_root / "merged_signal_return__WEB_PROOF_TEST.parquet"
    pd.DataFrame(rows).to_parquet(panel_path, index=False)
    context = {
        "paths": {"merged_signal_return_parquet": str(panel_path)},
        "artifacts": ({
            "merged_signal_return": {"sha256": sha256_file(panel_path)}
        } if include_source_hash else {}),
    }
    (run_root / "shared_evaluation_context__WEB_PROOF_TEST.json").write_text(
        json.dumps(context),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("direction", "expected_verdict"),
    [(1.0, "ACCEPT"), (-1.0, "REJECT")],
)
def test_web_factor_proof_replays_exact_oos_and_writes_bound_certificate(
    tmp_path: Path,
    direction: float,
    expected_verdict: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, selected = _plan(calendar["dates"])

    preregistration = prepare_web_factor_proof(
        workspace_root=root,
        plan=plan,
    )
    assert preregistration["registered_before_step4"] is True
    assert not (root / "objects" / "research_protocol" / "factor_proof_panel__WEB_PROOF_TEST.parquet").exists()
    _write_shared_panel(root, selected, direction=direction)

    result = finalize_web_factor_proof(workspace_root=root, plan=plan)

    assert result["status"] == "PASS"
    assert result["factor_verdict"] == expected_verdict
    assert result["formal_proof_eligible"] is True
    assert result["panel"]["period_count"] == 80
    certificate = json.loads(
        (root / result["factor_proof_certificate_ref"]).read_text(encoding="utf-8")
    )
    verifier = json.loads(
        (root / result["factor_proof_verifier_ref"]).read_text(encoding="utf-8")
    )
    assert certificate["declared_verdict"] == expected_verdict
    assert verifier["verdict"] == expected_verdict
    assert verifier["block_reasons"] == []
    assert finalize_web_factor_proof(workspace_root=root, plan=plan) == result
    if direction > 0:
        verifier["formal_proof_eligible"] = False
        (root / result["factor_proof_verifier_ref"]).write_text(
            json.dumps(verifier),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="final output binding mismatch"):
            finalize_web_factor_proof(workspace_root=root, plan=plan)


def test_web_factor_proof_blocks_any_oos_label_calendar_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, selected = _plan(calendar["dates"])
    prepare_web_factor_proof(workspace_root=root, plan=plan)
    _write_shared_panel(root, selected, direction=1.0, bad_label_date=True)

    with pytest.raises(ValueError, match="OOS label dates do not match"):
        finalize_web_factor_proof(workspace_root=root, plan=plan)


def test_web_factor_proof_preregistration_is_bound_to_exact_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, _selected = _plan(calendar["dates"])
    prepare_web_factor_proof(workspace_root=root, plan=plan)

    changed = deepcopy(plan)
    changed["research_object"]["formula_or_law"] = "-close"
    with pytest.raises(ValueError, match="preregistration binding mismatch"):
        validate_web_factor_proof_preregistration(root, changed)


def test_web_factor_proof_preregistration_binds_complete_spec(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, _selected = _plan(calendar["dates"])
    prepare_web_factor_proof(workspace_root=root, plan=plan)
    spec_path = web_factor_proof_paths(root, "WEB_PROOF_TEST")["spec"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["research_windows"]["is_window"] = "1900-01-01/1900-12-31"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ValueError, match="preregistration binding mismatch"):
        validate_web_factor_proof_preregistration(root, plan)


def test_risk_premium_preregisters_proof_controls_outside_formula_inputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, _selected = _plan(calendar["dates"])
    plan["economic_mechanism"]["claim_class"] = "risk_premium"

    prepare_web_factor_proof(workspace_root=root, plan=plan)

    spec = json.loads(
        (
            root
            / "objects/research_protocol/metric_verifier_spec__WEB_PROOF_TEST.json"
        ).read_text(encoding="utf-8")
    )
    assert plan["data_plan"]["daily_fields"] == ["close"]
    assert spec["panel"]["control_columns"] == ["total_mv", "turnover_rate"]


def test_web_factor_proof_requires_step4_source_panel_hash(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, selected = _plan(calendar["dates"])
    prepare_web_factor_proof(workspace_root=root, plan=plan)
    _write_shared_panel(
        root,
        selected,
        direction=1.0,
        include_source_hash=False,
    )

    with pytest.raises(ValueError, match="shared panel hash mismatch"):
        finalize_web_factor_proof(workspace_root=root, plan=plan)


def test_web_factor_proof_finalization_recovers_after_receipt_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, selected = _plan(calendar["dates"])
    prepare_web_factor_proof(workspace_root=root, plan=plan)
    _write_shared_panel(root, selected, direction=-1.0)
    paths = web_factor_proof_paths(root, "WEB_PROOF_TEST")
    write_atomic = web_factor_proof._write_json_atomic

    def interrupt_receipt(path: Path, payload: dict) -> None:
        if path == paths["finalization"]:
            raise RuntimeError("simulated receipt interruption")
        write_atomic(path, payload)

    monkeypatch.setattr(web_factor_proof, "_write_json_atomic", interrupt_receipt)
    with pytest.raises(RuntimeError, match="simulated receipt interruption"):
        finalize_web_factor_proof(workspace_root=root, plan=plan)
    assert paths["panel"].is_file()
    assert paths["release"].is_file()
    assert paths["bound_spec"].is_file()
    assert not paths["finalization"].exists()

    monkeypatch.setattr(web_factor_proof, "_write_json_atomic", write_atomic)
    result = finalize_web_factor_proof(workspace_root=root, plan=plan)
    assert result["status"] == "PASS"
    assert result["factor_verdict"] == "REJECT"
