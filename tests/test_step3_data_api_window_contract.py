from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_access.calendar import list_open_trade_dates
from factor_factory.data_access.paths import LocalTusharePaths


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step3():
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/run_step3.py"
    spec = importlib.util.spec_from_file_location("run_step3_window_contract_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _ready_resolution(dataset: str, **kwargs):
    status = "proxy_ready" if dataset == "minute_bar" else "ready"
    return {
        "dataset_id": dataset,
        "status": status,
        "catalog_path": "/tmp/factorforge_data_catalog.json",
        "daily_filter_policy": {
            "drop_suspended": True,
            "drop_limit_events": True,
            "invalid_days_do_not_enter_window": True,
            "minimum_effective_days": 10,
        },
        "coverage": {"row_count": 1},
        "request": kwargs,
    }


def test_data_api_query_payload_normalizes_current_end_date(monkeypatch):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")

    payload = run_step3.data_api_query_payload(
        "clean_daily_bar",
        {"start": "2016-01-01", "end": "current"},
        ["close"],
    )

    assert payload["start_date"] == "20160101"
    assert payload["end_date"] == "20260603"


def test_declared_sample_window_honors_source_window_start_only():
    run_step3 = _load_run_step3()

    result = run_step3.declared_sample_window(
        {
            "canonical_spec": {},
            "source_metadata": {
                "window_start": "2016-01-01",
                "calendar": "A-share trading days",
            },
        },
        {},
        {"start": "20100104", "end": "current", "calendar": "A-share trading days"},
    )

    assert result == {
        "start": "20160101",
        "end": "current",
        "calendar": "A-share trading days",
    }


def test_declared_sample_window_prefers_step2_requested_research_window():
    run_step3 = _load_run_step3()

    result = run_step3.declared_sample_window(
        {
            "canonical_spec": {},
        },
        {},
        {"start": "20100104", "end": "current", "calendar": "A-share trading days"},
        alpha_idea={
            "research_window_contract": {
                "scope": "local_IS_only",
                "requested_start": "2016-01-04",
                "requested_end": "2025-07-11",
            },
        },
    )

    assert result == {
        "start": "20160104",
        "end": "20250711",
        "calendar": "A-share trading days",
    }


def test_primary_daily_dataset_follows_frozen_step2_declaration():
    run_step3 = _load_run_step3()

    fsm = {
        "canonical_spec": {
            "preprocessing": [
                "Use daily_event_state_v1 so all event rows and exclusion reasons remain observable."
            ]
        }
    }

    assert run_step3.declared_primary_daily_dataset_id(fsm) == "daily_event_state_v1"


def test_primary_daily_dataset_defaults_without_declaration():
    run_step3 = _load_run_step3()
    assert run_step3.declared_primary_daily_dataset_id({"canonical_spec": {}}) == "clean_daily_bar"


def test_step4_contract_binds_declared_event_state_dataset():
    run_step3 = _load_run_step3()
    contract = run_step3.build_step4_data_contract(
        sample_window={"start": "20160104", "end": "20250711"},
        daily_resolution={"catalog_binding": {"catalog_sha256": "a" * 64}},
        daily_fields=["ts_code", "trade_date", "amount", "pct_chg"],
        primary_daily_dataset_id="daily_event_state_v1",
    )

    assert contract["primary_daily_dataset_id"] == "daily_event_state_v1"
    assert set(contract["full_queries"]) == {"daily_event_state_v1"}
    assert contract["full_queries"]["daily_event_state_v1"]["dataset"] == "daily_event_state_v1"
    assert set(contract["catalog_bindings"]) == {"daily_event_state_v1"}


def _calendar_paths(tmp_path: Path, *, bound_exchange: str | None) -> LocalTusharePaths:
    root = tmp_path / 'raw_tushare'
    calendar = root / '基础数据' / 'trade_cal.csv'
    calendar.parent.mkdir(parents=True)
    calendar.write_text(
        'cal_date,is_open\n20260105,1\n20260106,0\n',
        encoding='utf-8',
    )
    return LocalTusharePaths(
        root=root,
        daily_csv=root / '行情数据/daily.csv',
        adj_factor_csv=root / '行情数据/adj_factor.csv',
        daily_basic_dir=root / '行情数据/daily_basic_incremental',
        trade_cal_csv=calendar,
        stock_basic_csv=root / '基础数据/stock_basic.csv',
        stock_st_csv=root / '基础数据/stock_st.csv',
        stock_st_daily_csv=root / '基础数据/stock_st_daily.csv',
        source_label='test',
        trade_calendar_exchange=bound_exchange,
    )


def test_exchange_less_trade_calendar_requires_and_uses_explicit_sse_binding(tmp_path):
    paths = _calendar_paths(tmp_path, bound_exchange='SSE')
    assert list_open_trade_dates(
        start='20260105', end='20260106', exchange='SSE', paths=paths
    ) == ['20260105']


def test_exchange_less_trade_calendar_does_not_guess_exchange(tmp_path):
    paths = _calendar_paths(tmp_path, bound_exchange=None)
    with pytest.raises(ValueError, match='no matching explicit exchange binding'):
        list_open_trade_dates(
            start='20260105', end='20260106', exchange='SSE', paths=paths
        )


def test_enrich_report_local_daily_fields_emits_versioned_contract():
    run_step3 = _load_run_step3()
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20160104",
                "open": 10.0,
                "close": 10.1,
                "vol": 100.0,
                "amount": 1010.0,
                "pct_chg": 0.1,
            }
        ]
    )

    _enriched, contract = run_step3.enrich_report_local_daily_fields(frame, ["open", "close"])

    assert contract["version"] == "factorforge_derived_field_contract_v1"
    assert contract["validation_result"] == "PASS"
    assert contract["standard_formula_fields_added"] == []
    assert contract["required_formula_fields"] == ["close", "open"]
    assert contract["source_fields"] == ["close", "open"]
    assert contract["derived_fields"] == {}
    assert contract["clean_data_mutation"] is False


def test_enrich_report_local_daily_fields_emits_formula_operator_contracts():
    run_step3 = _load_run_step3()
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20160104",
                "open": 10.0,
                "close": 10.1,
                "vol": 100.0,
                "amount": 1010.0,
                "pct_chg": 0.1,
            }
        ]
    )
    formula_ir = {
        "root": {
            "type": "operator",
            "operator": "rank",
            "args": [
                {
                    "type": "operator",
                    "operator": "ts_rank",
                    "args": [
                        {"type": "field", "name": "close", "resolved_field": "close"},
                        {"type": "constant", "value": 10},
                    ],
                }
            ],
        }
    }

    _enriched, contract = run_step3.enrich_report_local_daily_fields(
        frame,
        ["close"],
        formula_ir=formula_ir,
    )

    derived = contract["derived_fields"]
    ts_rank_specs = [spec for spec in derived.values() if spec["operator"] == "ts_rank"]
    rank_specs = [spec for spec in derived.values() if spec["operator"] == "rank"]
    assert contract["validation_result"] == "PASS"
    assert contract["source_fields"] == ["close"]
    assert ts_rank_specs and ts_rank_specs[0]["lookback_window"] == 10
    assert ts_rank_specs[0]["sources"] == ["close"]
    assert ts_rank_specs[0]["output_unit"] == "rank_score"
    assert rank_specs and rank_specs[0]["rank_scope"] == "cross_sectional_by_trade_date"
    assert rank_specs[0]["output_unit"] == "rank_score"


def test_daily_step3a_snapshot_uses_query_safe_current_end(monkeypatch, tmp_path):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")
    monkeypatch.setattr(run_step3, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_step3, "WORKSPACE", tmp_path)
    monkeypatch.setattr(run_step3.pd.DataFrame, "to_parquet", lambda self, path, index=False: Path(path).write_text("parquet-smoke"))
    monkeypatch.setattr(run_step3, "materialize_daily_audit_csv", lambda *args, **kwargs: {"csv_output_policy": "no_csv"})

    calls = []

    def fake_resolve(dataset, **kwargs):
        calls.append(("resolve", dataset, kwargs))
        return _ready_resolution(dataset, **kwargs)

    class FakeResult:
        status = "ready"
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20160104",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "pre_close": 9.9,
                    "vol": 100.0,
                    "amount": 1010.0,
                    "pct_chg": 0.1,
                }
            ]
        )

        def to_metadata(self):
            return {"status": "ready"}

    def fake_fetch(dataset, **kwargs):
        calls.append(("fetch", dataset, kwargs))
        return FakeResult()

    monkeypatch.setattr(run_step3, "resolve_data_api_dataset", fake_resolve)
    monkeypatch.setattr(run_step3, "fetch_data_api_dataset", fake_fetch)

    result = run_step3.materialize_shared_daily_slice(
        "STEP3A_CURRENT_WINDOW_DAILY",
        {"start": "2016-01-01", "end": "current"},
        required_fields=["open", "pre_close"],
        formula_ir={
            "resolved_fields": {"open": "open", "pre_close": "pre_close"},
            "operator_set": ["divide", "minus", "negate"],
            "root": {},
        },
    )

    assert result["sample_window_actual"]["end"] == "20160808"
    assert result["step4_full_window"]["end"] == "20260603"
    assert result["step4_data_contract"]["full_queries"]["clean_daily_bar"]["end_date"] == "20260603"
    assert calls
    clean_daily_calls = [
        kwargs for _kind, dataset, kwargs in calls if dataset == "clean_daily_bar"
    ]
    assert clean_daily_calls
    assert all("pre_close" in kwargs["fields"] for kwargs in clean_daily_calls)
    assert "pre_close" in result["step4_data_contract"]["full_queries"]["clean_daily_bar"]["fields"]
    assert all(call[2].get("start") == "20160101" for call in calls)
    assert all(call[2].get("end") == "20160808" for call in calls)


def test_direct_code_calendar_role_is_not_treated_as_daily_field():
    run_step3 = _load_run_step3()
    fields = run_step3.formula_required_daily_fields({
        'canonical_spec': {
            'required_inputs': [
                'daily_df.pct_chg',
                'exchange_calendar.trade_date',
            ],
        },
        'implementation_contract': {
            'code_contract': {
                'required_fields': ['ts_code', 'trade_date', 'pct_chg', 'amount'],
                'input_schema': {
                    'daily_df': ['ts_code', 'trade_date', 'pct_chg', 'amount'],
                    'exchange_calendar': ['trade_date'],
                },
            },
        },
    })
    assert set(fields) == {'ts_code', 'trade_date', 'pct_chg', 'amount'}
    assert all(not field.startswith('exchange_calendar.') for field in fields)


def test_step3a_materializes_declared_calendar_and_uses_full_market(monkeypatch, tmp_path):
    run_step3 = _load_run_step3()
    monkeypatch.setattr(run_step3, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(run_step3, 'WORKSPACE', tmp_path)
    trade_cal = tmp_path / 'trade_cal.csv'
    trade_cal.write_text('exchange,cal_date,is_open\nSSE,20260105,1\n', encoding='utf-8')
    monkeypatch.setattr(
        run_step3,
        'LOCAL_TUSHARE',
        type('Paths', (), {'trade_cal_csv': trade_cal})(),
    )
    monkeypatch.setattr(
        run_step3,
        'list_open_trade_dates',
        lambda **_kwargs: ['20260105'],
    )
    monkeypatch.setattr(
        run_step3,
        'materialize_daily_audit_csv',
        lambda *args, **kwargs: {'csv_output_policy': 'no_csv'},
    )
    resolutions = []

    def fake_resolve(dataset, **kwargs):
        resolutions.append((dataset, kwargs))
        return _ready_resolution(dataset, **kwargs)

    class FakeResult:
        status = 'ready'
        frame = pd.DataFrame({
            'ts_code': ['000001.SZ', '000002.SZ', '000003.SZ'],
            'trade_date': ['20260105'] * 3,
            'pct_chg': [1.0, -1.0, 0.5],
            'amount': [100.0, 200.0, 300.0],
        })

        def to_metadata(self):
            return {'status': 'ready'}

    monkeypatch.setattr(run_step3, 'resolve_data_api_dataset', fake_resolve)
    monkeypatch.setattr(run_step3, 'fetch_data_api_dataset', lambda *args, **kwargs: FakeResult())

    result = run_step3.materialize_shared_daily_slice(
        'CALENDAR_ROLE',
        {'start': '2026-01-05', 'end': '2026-01-05'},
        required_fields=['ts_code', 'trade_date', 'pct_chg', 'amount'],
        requires_exchange_calendar=True,
    )

    assert result['snapshot_source'] == 'data_api_clean_daily_bar'
    assert Path(tmp_path / result['exchange_calendar_parquet']).exists()
    assert result['exchange_calendar_contract']['row_count'] == 1
    clean_requests = [kwargs for dataset, kwargs in resolutions if dataset == 'clean_daily_bar']
    assert clean_requests and all(kwargs['universe'] == 'a_share_all' for kwargs in clean_requests)
    assert 'exchange_calendar' in result['step4_data_contract']['additional_input_roles']


def test_minute_step3a_snapshot_resolution_uses_query_safe_current_end(monkeypatch, tmp_path):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")
    monkeypatch.setattr(run_step3, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_step3, "WORKSPACE", tmp_path)

    calls = []

    def fake_resolve(dataset, **kwargs):
        calls.append((dataset, kwargs))
        resolution = _ready_resolution(dataset, **kwargs)
        if dataset == "minute_bar":
            resolution["status"] = "blocked"
        return resolution

    monkeypatch.setattr(run_step3, "resolve_data_api_dataset", fake_resolve)

    result = run_step3.build_local_price_volume_snapshots(
        "STEP3A_CURRENT_WINDOW_MINUTE",
        {"start": "2016-01-01", "end": "current"},
    )

    assert result["snapshot_source"] == "missing_data_api_minute_or_daily"
    assert result["step4_data_contract"]["full_queries"]["clean_daily_bar"]["end_date"] == "20260603"
    assert result["step4_data_contract"]["full_queries"]["minute_bar"]["end_date"] == "20260603"
    assert {dataset for dataset, _kwargs in calls} == {"clean_daily_bar", "minute_bar"}
    assert all(kwargs.get("start") == "20160101" for _dataset, kwargs in calls)
    assert all(kwargs.get("end") == "20160808" for _dataset, kwargs in calls)
