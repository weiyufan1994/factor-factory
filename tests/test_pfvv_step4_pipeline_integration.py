from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO = Path(__file__).resolve().parents[1]
RUN_STEP4 = REPO / "skills/factor-forge-step4/scripts/run_step4.py"
CONTROLLER = REPO / "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_partitioned_v1.py"
BACKEND = REPO / "examples/mszq_intraday_momentum_pulse/pfvv_monthly_step4_backend_v1.py"
ENGINE_DIR = REPO / "examples/mszq_intraday_momentum_pulse/local_is_execution_engine"


def _load_run_step4() -> object:
    spec = importlib.util.spec_from_file_location("pfvv_step4_pipeline_run", RUN_STEP4)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_step4_current_factor_output_binding_rejects_static_override_conflicts(
    tmp_path: Path,
) -> None:
    module = _load_run_step4()
    target = tmp_path / "factor_values.parquet"
    with pytest.raises(ValueError, match="FACTOR_VALUES_ARG_CONFLICT"):
        module.custom_backend_config_with_step4_factor_output(
            {"factor_values_source": "step4_output", "args": ["--factor-values", "old.parquet"]},
            factor_parquet_path=target,
        )
    with pytest.raises(ValueError, match="FACTOR_VALUES_SOURCE_INVALID"):
        module.custom_backend_config_with_step4_factor_output(
            {"factor_values_source": "anything_else"}, factor_parquet_path=target,
        )


def test_prepared_pfvv_controller_reaches_current_step4_output_and_monthly_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise controller -> real Step4 caller -> custom backend on synthetic inputs.

    The custom prepared manifest names the deterministic Step4 output path
    before it exists.  It can only be read after this invocation's controller
    materializes that path; this catches stale/static factor-value reuse.
    """

    assert ENGINE_DIR.is_dir(), "packaged PFVV execution engine is required"
    report_id, factor_id = "PFVV_STEP4_PIPELINE_SYNTHETIC", "mszq_pfvv_source_baseline"
    canonical_root = tmp_path / "canonical-factorforge"
    canonical_root.mkdir()
    debug_root = tmp_path / "debug-root"
    debug_root.mkdir()
    # Direct Step4 debug policy deliberately switches artifact ownership to
    # this non-canonical root after its preflight.
    execution_root = debug_root
    state_root = tmp_path / "prepared-state"
    state_root.mkdir()
    dates = pd.bdate_range("2016-01-04", "2016-03-31")
    date_text = dates.strftime("%Y%m%d").tolist()
    codes = [f"{number:06d}.SZ" for number in range(1, 101)]

    day_paths: dict[str, str] = {}
    for day_index, day in enumerate(date_text):
        rel = f"daily/{day}.parquet"
        path = state_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        stock_index = np.arange(1, len(codes) + 1, dtype=float)
        # Both daily inputs vary by stock and time so the rolling PF/VV signal
        # is finite after warmup; this does not construct any market return.
        daily = pd.DataFrame({
            "ts_code": codes,
            "trade_date": day,
            "pf_daily": stock_index * (1.0 + 0.01 * ((day_index % 7) - 3)),
            "vv_daily": stock_index * (1.0 + 0.01 * (((day_index * 3) % 11) - 5)),
        })
        daily.to_parquet(path, index=False)
        day_paths[day] = rel

    daily_path = tmp_path / "daily.parquet"
    daily_rows = []
    execution_rows = []
    constraint_rows = []
    for day_index, day in enumerate(date_text):
        for number, code in enumerate(codes, start=1):
            price = 10.0 + number / 100.0 + day_index / 10_000.0
            daily_rows.append({"ts_code": code, "trade_date": day, "close": price})
            execution_rows.append({
                "ts_code": code,
                "trade_date": day,
                "vwap_0945_1000_unadjusted": price,
                "execution_bar_count": 16,
                "price_basis": "UNADJUSTED_AMOUNT_OVER_VOL",
                "execution_price_status": "OK",
            })
            constraint_rows.append({
                "ts_code": code, "trade_date": day, "constraint_complete": True,
                "st_new_buy_blocked": False, "pretrade_buy_blocked": False,
                "pretrade_sell_blocked": False, "is_st_asof_trade": False,
                "up_limit": 1000.0, "down_limit": 0.001, "unknown_reason": "",
                "delisting_execution_policy": "NO_STATUS_EVIDENCE",
                "historicalstatus_present": False, "listing_status": "UNKNOWN",
                "delist_cash_settlement_unadjusted": np.nan,
            })
    pd.DataFrame(daily_rows).to_parquet(daily_path, index=False)
    execution_path = tmp_path / "execution.parquet"
    pd.DataFrame(execution_rows).to_parquet(execution_path, index=False)
    constraints_path = tmp_path / "constraints.parquet"
    pd.DataFrame(constraint_rows).to_parquet(constraints_path, index=False)
    measurement_path = tmp_path / "measurement.parquet"
    pd.DataFrame(
        [{"ts_code": code, "trade_date": day} for day in date_text for code in codes]
    ).to_parquet(measurement_path, index=False)
    prices_path = tmp_path / "prices.parquet"
    pd.DataFrame([
        {
            "ts_code": row["ts_code"], "trade_date": row["trade_date"],
            "close_unadjusted": row["close"], "adj_factor": 1.0,
        }
        for row in daily_rows
    ]).to_parquet(prices_path, index=False)
    calendar_path = tmp_path / "calendar.parquet"
    pd.DataFrame({"trade_date": date_text, "is_open": True}).to_parquet(calendar_path, index=False)

    run_dir = execution_root / "runs" / report_id
    step4_factor_path = run_dir / f"factor_values__{report_id}.parquet"
    assert not step4_factor_path.exists()
    backend_inputs = tmp_path / "backend_inputs.json"
    _write_json(backend_inputs, {
        "schema_id": "pfvv_monthly_step4_prepared_inputs_v1",
        "report_id": report_id,
        "factor_values_path": str(step4_factor_path),
        "measurement_domain_path": str(measurement_path),
        "daily_prices_path": str(prices_path),
        "execution_vwap_path": str(execution_path),
        "normalized_constraints_path": str(constraints_path),
        "calendar_path": str(calendar_path),
        "complete_months": ["2016-01", "2016-02"],
    })
    local_inputs = {
        "input_mode": "derived_state_with_daily",
        "daily_df_parquet": str(daily_path),
        "derived_state_root": str(state_root),
        "sample_window_actual": {"start": date_text[0], "end": date_text[-1]},
        "pfvv_prepared_daily_state": {
            "contract_version": "pfvv_prepared_daily_state_v1",
            "measurement_authority": "pfvv_source_baseline_v1",
            "required_columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
            "calendar_dates": date_text,
            "day_paths": day_paths,
        },
    }
    fsm = {
        "report_id": report_id,
        "factor_id": factor_id,
        "implementation_mode": "direct_code",
        "implementation_contract": {"mode": "direct_code", "code_contract": {
            "performance_scope": {"formal_step4_full_window_execution_allowed": True},
        }},
        "canonical_spec": {"standard_formula_fields_contract": {"required_standard_formula_fields": []}},
    }
    dpm = {
        "report_id": report_id, "factor_id": factor_id,
        "sample_window": {"start": date_text[0], "end": date_text[-1]},
        "field_mapping": {"close": "close"}, "data_sources": ["synthetic_prepared_state"],
        "sparse_signal_allowed": True, "local_input_paths": local_inputs,
    }
    handoff = {
        "report_id": report_id,
        "implementation_path": str(CONTROLLER),
        "local_input_paths": local_inputs,
        "evaluation_plan": {
            "primary_backend": "pfvv_monthly_cash_v1",
            "frequency": "monthly", "scope": "local_is_only",
            "backends": [{
                "name": "pfvv_monthly_cash_v1", "script_path": str(BACKEND),
                "factor_values_source": "step4_output",
                "args": [
                    "--prepared-inputs", str(backend_inputs),
                    "--execution-engine-path", str(ENGINE_DIR),
                    "--execution-engine-module", "mszq_step4_portfolio_evaluator_candidate_v1",
                ],
            }],
        },
    }
    _write_json(execution_root / "objects/factor_spec_master" / f"factor_spec_master__{report_id}.json", fsm)
    _write_json(execution_root / "objects/data_prep_master" / f"data_prep_master__{report_id}.json", dpm)
    _write_json(execution_root / "objects/handoff" / f"handoff_to_step4__{report_id}.json", handoff)

    monkeypatch.setenv("FACTORFORGE_ROOT", str(canonical_root))
    monkeypatch.setenv("FACTORFORGE_ALLOW_DIRECT_STEP", "1")
    monkeypatch.setenv("FACTORFORGE_DEBUG_ROOT", str(debug_root))
    monkeypatch.setenv("FACTORFORGE_LOCAL_IS_ONLY", "1")
    module = _load_run_step4()
    monkeypatch.setattr(sys, "argv", [str(RUN_STEP4), "--report-id", report_id])
    actual_dispatch = module.write_backend_payloads

    def dispatch_after_parent_release(*args, **kwargs):
        caller = inspect.currentframe().f_back.f_locals
        for name in ("result_df", "daily_df", "signal_daily_df", "minute_df", "controller_result"):
            assert caller[name] is None, name
        assert caller["null_ratio"]["factor_value"] > 0
        assert caller["duplicate_ratio"]["ts_code_trade_date"] == 0
        return actual_dispatch(*args, **kwargs)

    monkeypatch.setattr(module, "write_backend_payloads", dispatch_after_parent_release)
    module.main()

    factor_values = pd.read_parquet(step4_factor_path)
    assert {"factor_value", "warmup", "PF", "VV"}.issubset(factor_values.columns)
    run_master = json.loads(
        (execution_root / "objects/factor_run_master" / f"factor_run_master__{report_id}.json").read_text()
    )
    assert run_master["signal_column"] == "factor_value"
    assert pd.api.types.is_float_dtype(factor_values["factor_value"])
    payload_path = Path(run_master["evaluation_results"]["backend_runs"][0]["payload_path"])
    payload = json.loads(payload_path.read_text())
    assert payload["backend"] == "pfvv_monthly_cash_v1"
    assert payload["portfolio_contract"]["group_count"] == 10
    assert payload["ic_summary"]["label_contract"] == "INDEPENDENT_20_TRADING_DAYS__NOT_MONTHLY_PORTFOLIO_NAV"
    assert payload["summary"]["monthly_nav_and_20_day_ic_separate"] is True
