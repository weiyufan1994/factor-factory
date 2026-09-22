from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.evo_data_boundary import (
    BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID,
    build_closed_pre_release_data_resolution,
    canonical_step3_sample_query,
    project_pre_release_data_access,
    validate_closed_pre_release_data_resolution,
)


REPORT = "WEB_PV_FORCED_SELL_EXHAUSTION_LOW_HOLD_V1_20260813_678afca106"
FACTOR = "PV_FORCED_SELL_EXHAUSTION_LOW_HOLD_V1"
FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "pct_chg",
    "turnover_rate",
    "ln_mcap_free",
    "volume_ratio",
]
WINDOWS = {
    "is_start": "2016-01-01",
    "is_end": "2022-08-31",
    "oos_start": "2022-09-01",
    "oos_end": "2023-02-28",
    "purge_days": 5,
    "embargo_days": 5,
}
SAMPLE_QUERY = {
    "dataset": "clean_daily_bar",
    "start_date": "20160101",
    "end_date": "20160808",
    "universe": ["000001.SZ", "000002.SZ"],
    "fields": FIELDS,
    "frequency": "daily",
}
FSM = {
    "report_id": REPORT,
    "factor_id": FACTOR,
    "canonical_spec": {
        "required_inputs": ["close", "low", "vol"],
        "formula_ir": {
            "required_fields": ["close", "low", "vol"],
            "resolved_fields": {
                "close": "close",
                "low": "low",
                "vol": "vol",
            },
        },
    },
    "evaluation_contract": {
        "proof_control_columns": [
            "turnover_rate",
            "ln_mcap_free",
            "volume_ratio",
        ]
    },
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_artifact(fixture: dict, frame: pd.DataFrame) -> None:
    frame.to_parquet(fixture["artifact"], index=False)
    key_hash = hashlib.sha256(
        frame[["ts_code", "trade_date"]]
        .astype(str)
        .reset_index(drop=True)
        .to_csv(index=False)
        .encode("utf-8")
    ).hexdigest()
    sort_contract = fixture["local_inputs"]["sort_contract"]
    sort_contract["data_hash"] = key_hash
    sort_contract["row_count"] = len(frame)
    sort_contract["schema"] = list(frame.columns)
    fixture["local_inputs"]["daily_io_contract"]["parquet_rows_written"] = len(
        frame
    )
    coverage = fixture["resolution"]["clean_daily_bar"]["sample_read"][
        "coverage"
    ]
    coverage.update(
        {
            "row_count": len(frame),
            "date_count": int(frame["trade_date"].nunique()),
            "ticker_count": int(frame["ts_code"].nunique()),
        }
    )


def _frame() -> pd.DataFrame:
    all_dates = pd.bdate_range("2016-01-04", "2016-08-08")
    dates = all_dates[
        [round(index * (len(all_dates) - 1) / 84) for index in range(85)]
    ]
    rows = []
    for ticker_index, ticker in enumerate(("000001.SZ", "000002.SZ")):
        for index, date in enumerate(dates):
            close = 10.0 + ticker_index + index / 100
            rows.append(
                {
                    "ts_code": ticker,
                    "trade_date": date.strftime("%Y%m%d"),
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "vol": 1000.0 + index,
                    "amount": 10000.0 + index,
                    "pct_chg": 0.1,
                    "turnover_rate": 1.0,
                    "ln_mcap_free": 20.0,
                    "volume_ratio": 1.1,
                }
            )
    return pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _fixture(tmp_path: Path) -> dict:
    workspace = tmp_path / "factor_scope"
    factorforge = workspace / "research_R5"
    frame = _frame()
    relative = (
        f"research_R5/runs/{REPORT}/step3a_local_inputs/"
        f"daily_input__{REPORT}.parquet"
    )
    artifact = workspace / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(artifact, index=False)

    key_hash = hashlib.sha256(
        frame[["ts_code", "trade_date"]]
        .astype(str)
        .reset_index(drop=True)
        .to_csv(index=False)
        .encode("utf-8")
    ).hexdigest()
    io_contract = {
        "version": "factorforge_step3a_daily_io_contract_v1",
        "formal_evidence_format": "parquet",
        "performance_path": "parquet",
        "audit_path": "none",
        "csv_output_policy": "no_csv",
        "csv_rows_written": 0,
        "parquet_rows_written": len(frame),
        "csv_sample_strategy": "none",
        "full_csv_available": False,
        "schema_parity_required": False,
        "value_parity_required": False,
        "csv_required_for_audit": False,
        "parquet_required_for_performance": True,
        "sample_schema_parity": None,
        "full_csv_absent_validated": True,
        "full_csv_absence_reason": "step3a_no_csv_policy",
        "sort_contract": {
            "version": "factorforge_sort_contract_v1",
            "sorted_by": ["ts_code", "trade_date"],
            "row_count": len(frame),
            "key_dtype": {
                "ts_code": str(frame["ts_code"].dtype),
                "trade_date": str(frame["trade_date"].dtype),
            },
            "source": "step3a_local_input",
            "data_hash": key_hash,
            "schema": list(frame.columns),
            "duplicate_key_check": True,
            "sample_sortedness_check": True,
        },
    }
    derived = {
        "version": "factorforge_derived_field_contract_v1",
        "validation_result": "PASS",
        "standard_formula_fields_added": [],
        "required_formula_fields": ["close", "low", "vol"],
        "source_fields": ["close", "low", "vol"],
        "derived_fields": {},
        "report_local_only": True,
        "clean_data_mutation": False,
    }
    local_inputs = {
        "snapshot_source": "data_api_clean_daily_bar",
        "primary_dataset": "clean_daily_bar",
        "input_mode": "daily_only",
        "daily_df_parquet": relative,
        "preferred_daily_format": "parquet",
        "daily_io_contract": io_contract,
        "sort_contract": io_contract["sort_contract"],
        "derived_field_contract": derived,
    }

    catalog_columns = [*frame.columns, "catalog_wide_extra"]
    catalog = tmp_path / "data_catalog.json"
    _write_json(
        catalog,
        {
            "datasets": [
                {
                    "dataset_id": "clean_daily_bar",
                    "status": "ready",
                    "uri": "s3://private/clean_daily_bar.parquet",
                    "columns": catalog_columns,
                    "daily_filter_policy": {
                        "drop_suspended": True,
                        "drop_limit_events": True,
                        "invalid_days_do_not_enter_window": True,
                        "minimum_effective_days": 10,
                        "private_path": "/must/not/project",
                    },
                }
            ]
        },
    )
    catalog_sha = _sha256(catalog)
    _write_json(
        factorforge / "identity/data_catalog_summary.json",
        {
            "version": "factorforge_web_data_catalog_summary_v2",
            "read_only": True,
            "active_catalog_admission": {
                "verdict": "PASS",
                "catalog_sha256": catalog_sha,
                "formal_dataset_qa_implied": False,
            },
            "catalogs": [
                {
                    "catalog_sha256": catalog_sha,
                    "entries": [
                        {
                            "name": "clean_daily_bar",
                            "catalog_membership": "active_catalog_member",
                            "columns": catalog_columns,
                            "host_information_policy_attestation": {
                                "version": "factorforge_host_information_policy_attestation_v1",
                                "verdict": "PASS",
                                "rule_id": "clean_daily_bar_pit_guarantees_v1",
                                "formation_time": "daily_close",
                                "future_observations_excluded": True,
                            },
                        }
                    ],
                }
            ],
        },
    )
    coverage = {
        "row_count": len(frame),
        "date_count": int(frame["trade_date"].nunique()),
        "ticker_count": int(frame["ts_code"].nunique()),
    }
    sample_read = {
        "dataset_id": "clean_daily_bar",
        "status": "ready",
        "query": {
            **SAMPLE_QUERY,
            # Independent DataQuery normalizes a symbol list to a tuple.
            "universe": tuple(SAMPLE_QUERY["universe"]),
        },
        "schema": {
            # The Data API metadata describes the catalog-wide schema; the
            # bounded frame itself contains only keys/query fields/enrichment.
            "columns": ["ts_code", "trade_date", *catalog_columns[2:]],
            "date_column": "trade_date",
            "symbol_column": "ts_code",
            "schema_hash": "catalog-schema-hash",
        },
        "coverage": coverage,
        "resolved_fields": {field: field for field in FIELDS},
    }
    resolution = {
        "clean_daily_bar": {
            "dataset_id": "clean_daily_bar",
            "status": "ready",
            "catalog_path": str(catalog),
            "request": copy.deepcopy(SAMPLE_QUERY),
            "resolved_fields": {field: field for field in FIELDS},
            "sample_read": sample_read,
        }
    }
    step4_contract = {
        "version": "factorforge_step4_data_contract_v1",
        "producer": "step3a",
        "data_api_package": "factorforge_data_api",
        "catalog_path": "/private/catalog.json",
        "full_queries": {
            "clean_daily_bar": {
                **SAMPLE_QUERY,
                "start_date": "20160101",
                "end_date": "20220831",
                "universe": "a_share_all",
                "catalog_path": "/private/catalog.json",
            }
        },
        "sample_queries": {
            "clean_daily_bar": {
                **SAMPLE_QUERY,
                "start_date": "20160101",
                "end_date": "20220831",
            }
        },
        "formal_factor_values_owner": "Step4",
    }
    seed = {
        "local_input_paths": {},
        "data_api_resolution": {},
        "step4_data_contract": copy.deepcopy(step4_contract),
    }
    project_pre_release_data_access(seed, WINDOWS)
    canonical_contract = seed["step4_data_contract"]
    return {
        "workspace": workspace,
        "factorforge": factorforge,
        "artifact": artifact,
        "artifact_relative": relative,
        "catalog": catalog,
        "local_inputs": local_inputs,
        "resolution": resolution,
        "step4_contract": canonical_contract,
        "derived": derived,
    }


def _build(fixture: dict) -> dict:
    return build_closed_pre_release_data_resolution(
        source_resolution=fixture["resolution"],
        local_inputs=fixture["local_inputs"],
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        required_fields=["close", "low", "vol"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
    )


def test_r5_closed_sample_projection_positive_and_exact_replay(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    projection = _build(fixture)
    clean = projection["clean_daily_bar"]

    assert projection["identity"] == {"report_id": REPORT, "factor_id": FACTOR}
    assert clean["frozen_is_window"] == {"start": "20160101", "end": "20220831"}
    assert clean["actual_fetch_query"] == SAMPLE_QUERY
    assert clean["observed_artifact_window"]["start"] == "20160104"
    assert clean["observed_artifact_window"]["end"] == "20160808"
    assert clean["coverage"]["row_count"] == 170
    assert clean["coverage"]["ticker_count"] == 2
    assert clean["formal_dataset_qa"] is False
    assert clean["full_is_calendar_coverage"] is False
    assert clean["formal_factor_values"] is False
    assert clean["local_artifact_replay"]["remote_worker_read_performed"] is False
    assert clean["step4_full_is_receipt_required"] is True
    serialized = json.dumps(projection, sort_keys=True)
    assert "s3://" not in serialized
    assert "/private/" not in serialized

    reasons = validate_closed_pre_release_data_resolution(
        projection,
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        catalog_path=fixture["catalog"],
        required_fields=["close", "low", "vol"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
        expected_artifact_relative=fixture["artifact_relative"],
    )
    assert reasons == []


@pytest.mark.parametrize(
    "mutator",
    [
        lambda proof: proof["identity"].update(report_id="OTHER"),
        lambda proof: proof["clean_daily_bar"]["sample_artifact"].update(sha256="0" * 64),
        lambda proof: proof["clean_daily_bar"]["actual_fetch_query"].update(end_date="20220901"),
        lambda proof: proof["clean_daily_bar"]["point_in_time_policy"].update(verdict="NOT_ATTESTED"),
        lambda proof: proof["clean_daily_bar"]["coverage"].update(duplicate_key_count=1),
        lambda proof: proof["clean_daily_bar"]["local_artifact_replay"].update(remote_worker_read_performed=True),
    ],
)
def test_r5_closed_sample_projection_tamper_fails_exact_replay(
    tmp_path: Path, mutator
) -> None:
    fixture = _fixture(tmp_path)
    projection = _build(fixture)
    mutator(projection)
    reasons = validate_closed_pre_release_data_resolution(
        projection,
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        catalog_path=fixture["catalog"],
        required_fields=["close", "low", "vol"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
        expected_artifact_relative=fixture["artifact_relative"],
    )
    assert reasons
    assert BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID in ";".join(reasons)


def test_project_preserves_nonsecret_consumer_contracts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    projection = _build(fixture)
    payload = {
        "local_input_paths": copy.deepcopy(fixture["local_inputs"]),
        "data_api_resolution": projection,
        "step4_data_contract": copy.deepcopy(fixture["step4_contract"]),
    }
    project_pre_release_data_access(payload, WINDOWS)

    local = payload["local_input_paths"]
    assert local["derived_field_contract"] == fixture["derived"]
    assert local["sort_contract"]["key_dtype"]
    assert local["sort_contract"]["source"] == "step3a_local_input"
    assert local["daily_df_parquet"] == fixture["artifact_relative"]
    assert payload["data_api_resolution"] == projection


def test_full_is_query_may_span_years_but_actual_sample_must_be_bounded(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    assert _build(fixture)
    fixture["resolution"]["clean_daily_bar"]["request"]["end_date"] = "20220831"
    fixture["resolution"]["clean_daily_bar"]["sample_read"]["query"]["end_date"] = "20220831"
    with pytest.raises(ValueError, match="sample_query.not_bounded"):
        _build(fixture)


def test_canonical_query_exactly_replays_r5_proof_controls() -> None:
    query = canonical_step3_sample_query(fsm=FSM, research_windows=WINDOWS)
    assert query == SAMPLE_QUERY


def test_s3_tuple_universe_and_catalog_wide_schema_normalize_to_closed_query(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    assert isinstance(
        fixture["resolution"]["clean_daily_bar"]["sample_read"]["query"][
            "universe"
        ],
        tuple,
    )
    projection = _build(fixture)
    assert projection["clean_daily_bar"]["actual_fetch_query"] == SAMPLE_QUERY
    assert "catalog_wide_extra" in projection["clean_daily_bar"][
        "source_read_metadata"
    ]["schema"]["columns"]
    assert "catalog_wide_extra" not in projection["clean_daily_bar"]["schema"][
        "columns"
    ]


@pytest.mark.parametrize("status_location", ["resolution", "sample_read"])
def test_proxy_ready_source_cannot_be_promoted_to_ready_sample_evidence(
    tmp_path: Path,
    status_location: str,
) -> None:
    fixture = _fixture(tmp_path)
    clean = fixture["resolution"]["clean_daily_bar"]
    target = clean if status_location == "resolution" else clean["sample_read"]
    target["status"] = "proxy_ready"
    with pytest.raises(ValueError, match="SAMPLE_DATA_EVIDENCE_MISSING"):
        _build(fixture)


def test_step4_full_query_fields_must_exactly_match_canonical_sample_fields(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["step4_contract"]["full_queries"]["clean_daily_bar"][
        "fields"
    ].remove("volume_ratio")
    with pytest.raises(ValueError, match="full_query_contract"):
        _build(fixture)


def test_catalog_wide_schema_must_cover_every_actual_query_field(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["resolution"]["clean_daily_bar"]["sample_read"]["schema"][
        "columns"
    ].remove("ln_mcap_free")
    with pytest.raises(ValueError, match="sample_read_schema_query_fields"):
        _build(fixture)


@pytest.mark.parametrize("mode", ["drop", "null"])
def test_local_artifact_must_cover_non_null_r5_proof_control(
    tmp_path: Path,
    mode: str,
) -> None:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    if mode == "drop":
        frame = frame.drop(columns=["volume_ratio"])
    else:
        frame["volume_ratio"] = float("nan")
    frame.to_parquet(fixture["artifact"], index=False)
    with pytest.raises(
        ValueError,
        match="sample_artifact.(fields|required_nulls|non_finite)",
    ):
        _build(fixture)


def test_forbidden_outcome_proof_control_blocks_canonical_query() -> None:
    fsm = copy.deepcopy(FSM)
    fsm["evaluation_contract"]["proof_control_columns"].append(
        "forward_return_label"
    )
    with pytest.raises(ValueError, match="forbidden_fields"):
        canonical_step3_sample_query(fsm=fsm, research_windows=WINDOWS)


def test_forbidden_logical_control_cannot_be_laundered_through_physical_alias() -> None:
    fsm = copy.deepcopy(FSM)
    fsm["evaluation_contract"]["proof_control_columns"].append("forward_label")
    fsm["canonical_spec"]["formula_ir"]["resolved_fields"][
        "forward_label"
    ] = "close"
    with pytest.raises(ValueError, match="forbidden_fields"):
        canonical_step3_sample_query(fsm=fsm, research_windows=WINDOWS)


def test_plain_non_evo_field_selector_preserves_target_like_legacy_field() -> None:
    run_step3 = _load_script(
        "run_step3_non_evo_selector_compat",
        "skills/factor-forge-step3/scripts/run_step3.py",
    )
    assert "target_weight" in run_step3.select_clean_daily_fields_for_formula(
        ["target_weight"],
        {},
    )


def _volume_alias_fixture(tmp_path: Path) -> dict:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame["volume"] = frame["vol"]
    frame.to_parquet(fixture["artifact"], index=False)
    fixture["local_inputs"]["derived_field_contract"].update(
        {
            "standard_formula_fields_added": ["volume"],
            "required_formula_fields": ["close", "low", "vol", "volume"],
            "derived_fields": {
                "volume": {
                    "operator": "alias",
                    "sources": ["vol"],
                    "rule": "alias(volume <- vol)",
                    "source_units": {"vol": "documented_volume_unit"},
                    "output_unit": "documented_volume_unit",
                    "leakage_policy": "no future data",
                }
            },
        }
    )
    return fixture


def _build_volume_alias(fixture: dict) -> dict:
    return build_closed_pre_release_data_resolution(
        source_resolution=fixture["resolution"],
        local_inputs=fixture["local_inputs"],
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        required_fields=["close", "low", "vol", "volume"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
    )


def test_standard_volume_alias_is_bound_to_nonsecret_derived_lineage(
    tmp_path: Path,
) -> None:
    fixture = _volume_alias_fixture(tmp_path)
    projection = _build_volume_alias(fixture)
    clean = projection["clean_daily_bar"]
    assert clean["resolved_fields"]["volume"] == "volume"
    assert clean["physical_source_fields"]["volume"] == ["vol"]
    assert clean["derived_field_lineage"]["derived_fields"]["volume"][
        "leakage_policy"
    ] == "no future data"


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator", "divide"),
        ("sources", ["close"]),
        ("rule", "alias(volume <- close)"),
    ],
)
def test_standard_volume_alias_semantic_tamper_is_rejected(
    tmp_path: Path,
    field: str,
    value,
) -> None:
    fixture = _volume_alias_fixture(tmp_path)
    fixture["local_inputs"]["derived_field_contract"]["derived_fields"][
        "volume"
    ][field] = value
    with pytest.raises(ValueError, match="derived_lineage.semantics.volume"):
        _build_volume_alias(fixture)


def _adv20_fixture(tmp_path: Path) -> dict:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame["adv20"] = frame.groupby("ts_code", sort=False)["vol"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    _rewrite_artifact(fixture, frame)
    fixture["local_inputs"]["derived_field_contract"].update(
        {
            "standard_formula_fields_added": ["adv20"],
            "required_formula_fields": ["close", "low", "vol", "adv20"],
            "derived_fields": {
                "adv20": {
                    "operator": "mean",
                    "sources": ["vol"],
                    "rule": "rolling_mean(vol,20)",
                    "source_units": {"vol": "documented_volume_unit"},
                    "output_unit": "documented_volume_unit",
                    "leakage_policy": "no future data",
                    "lookback_window": 20,
                }
            },
        }
    )
    return fixture


def _producer_shaped_adv20_fixture(tmp_path: Path) -> dict:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame["volume"] = frame["vol"]
    frame["adv20"] = frame.groupby("ts_code", sort=False)["volume"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    _rewrite_artifact(fixture, frame)
    fixture["local_inputs"]["derived_field_contract"].update(
        {
            "standard_formula_fields_added": ["volume", "adv20"],
            "required_formula_fields": ["close", "low", "vol", "adv20"],
            "derived_fields": {
                "volume": {
                    "operator": "alias",
                    "sources": ["vol"],
                    "rule": "alias(volume <- vol)",
                    "source_units": {"vol": "documented_volume_unit"},
                    "output_unit": "documented_volume_unit",
                    "leakage_policy": "no future data",
                },
                "adv20": {
                    "operator": "mean",
                    "sources": ["volume"],
                    "rule": "rolling_mean(volume,20)",
                    "source_units": {
                        "volume": "documented_volume_unit"
                    },
                    "output_unit": "documented_volume_unit",
                    "leakage_policy": "no future data",
                    "lookback_window": 20,
                },
            },
        }
    )
    return fixture


def _build_adv20(fixture: dict) -> dict:
    return build_closed_pre_release_data_resolution(
        source_resolution=fixture["resolution"],
        local_inputs=fixture["local_inputs"],
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        required_fields=["close", "low", "vol", "adv20"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
    )


def _validate_adv20(fixture: dict, projection: dict) -> list[str]:
    return validate_closed_pre_release_data_resolution(
        projection,
        research_windows=WINDOWS,
        workspace_root=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        catalog_path=fixture["catalog"],
        required_fields=["close", "low", "vol", "adv20"],
        report_id=REPORT,
        factor_id=FACTOR,
        expected_sample_query=SAMPLE_QUERY,
        step4_data_contract=fixture["step4_contract"],
        expected_artifact_relative=fixture["artifact_relative"],
    )


def test_adv20_allows_only_per_ticker_prefix_warmup_nulls(tmp_path: Path) -> None:
    fixture = _adv20_fixture(tmp_path)
    projection = _build_adv20(fixture)
    check = projection["clean_daily_bar"]["derived_field_warmup_checks"][
        "adv20"
    ]
    assert check == {
        "policy": "per_ticker_prefix_only",
        "lookback_window": 20,
        "allowed_warmup_prefix_rows_per_ticker": 19,
        "warmup_null_count": 38,
        "post_warmup_null_count": 0,
        "post_warmup_non_finite_count": 0,
        "valid_sample_count": 132,
        "ticker_count": 2,
    }
    assert projection["clean_daily_bar"]["coverage"][
        "required_field_null_counts"
    ]["adv20"] == 38
    assert _validate_adv20(fixture, projection) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator", "divide"),
        ("rule", "alias(volume <- close)"),
    ],
)
def test_producer_shaped_adv20_recursive_volume_tamper_fails_replay(
    tmp_path: Path,
    field: str,
    value,
) -> None:
    fixture = _producer_shaped_adv20_fixture(tmp_path)
    projection = _build_adv20(fixture)
    assert _validate_adv20(fixture, projection) == []
    projection["clean_daily_bar"]["derived_field_lineage"][
        "derived_fields"
    ]["volume"][field] = value
    reasons = _validate_adv20(fixture, projection)
    assert reasons
    assert "derived_lineage.semantics.volume" in ";".join(reasons)


def test_adv20_post_warmup_null_is_rejected(tmp_path: Path) -> None:
    fixture = _adv20_fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    ticker_rows = frame.index[frame["ts_code"] == "000001.SZ"]
    frame.loc[ticker_rows[20], "adv20"] = float("nan")
    _rewrite_artifact(fixture, frame)
    with pytest.raises(ValueError, match="derived_warmup.post_warmup_null.adv20"):
        _build_adv20(fixture)


def test_adv20_requires_exact_contiguous_warmup_prefix(tmp_path: Path) -> None:
    fixture = _adv20_fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    first_ticker_row = frame.index[frame["ts_code"] == "000001.SZ"][0]
    frame.loc[first_ticker_row, "adv20"] = frame.loc[
        first_ticker_row, "vol"
    ]
    _rewrite_artifact(fixture, frame)
    with pytest.raises(ValueError, match="derived_warmup.prefix_pattern.adv20"):
        _build_adv20(fixture)


def test_adv20_lineage_lookback_must_match_field_contract(tmp_path: Path) -> None:
    fixture = _adv20_fixture(tmp_path)
    fixture["local_inputs"]["derived_field_contract"]["derived_fields"][
        "adv20"
    ]["lookback_window"] = 19
    with pytest.raises(ValueError, match="derived_lineage.lookback.adv20"):
        _build_adv20(fixture)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda proof: proof["clean_daily_bar"]["derived_field_lineage"][
            "derived_fields"
        ]["adv20"].update(lookback_window=19),
        lambda proof: proof["clean_daily_bar"]["derived_field_lineage"][
            "derived_fields"
        ]["adv20"].update(operator="alias"),
        lambda proof: proof["clean_daily_bar"]["derived_field_lineage"][
            "derived_fields"
        ]["adv20"].update(sources=["close"]),
        lambda proof: proof["clean_daily_bar"]["derived_field_lineage"][
            "derived_fields"
        ]["adv20"].update(rule="rolling_mean(close,20)"),
        lambda proof: proof["clean_daily_bar"][
            "derived_field_warmup_checks"
        ]["adv20"].update(warmup_null_count=37),
    ],
)
def test_adv20_projection_lineage_and_warmup_tamper_fail_replay(
    tmp_path: Path,
    mutator,
) -> None:
    fixture = _adv20_fixture(tmp_path)
    projection = _build_adv20(fixture)
    mutator(projection)
    reasons = _validate_adv20(fixture, projection)
    assert reasons
    assert BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID in ";".join(reasons)


def test_sample_artifact_hardlink_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    os.link(fixture["artifact"], tmp_path / "second-link.parquet")
    with pytest.raises(ValueError, match="sample_artifact.unsafe_read"):
        _build(fixture)


def test_sample_artifact_intermediate_symlink_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original_dir = fixture["artifact"].parent
    moved_dir = tmp_path / "moved-step3-inputs"
    original_dir.rename(moved_dir)
    original_dir.symlink_to(moved_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="sample_artifact.unsafe_read"):
        _build(fixture)


def test_sample_artifact_symbols_must_exactly_match_requested_list_universe(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame["ts_code"] = frame["ts_code"].replace(
        {"000001.SZ": "600000.SH", "000002.SZ": "600001.SH"}
    )
    _rewrite_artifact(fixture, frame)
    with pytest.raises(ValueError, match="universe_membership"):
        _build(fixture)


def test_sample_artifact_trade_dates_must_be_real_calendar_dates(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame.loc[0, "trade_date"] = "20160230"
    frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    _rewrite_artifact(fixture, frame)
    with pytest.raises(ValueError, match="trade_date_invalid"):
        _build(fixture)


def test_sample_artifact_query_fields_must_be_finite(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    frame = pd.read_parquet(fixture["artifact"])
    frame["volume_ratio"] = float("inf")
    _rewrite_artifact(fixture, frame)
    with pytest.raises(ValueError, match="non_finite.volume_ratio"):
        _build(fixture)


def _load_script(name: str, relative: str):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nested_workspace_build_project_and_full_validator_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    projection = _build(fixture)
    prep = {
        "report_id": REPORT,
        "factor_id": FACTOR,
        "feasibility": "ready",
        "sample_window": {"start": "2016-01-01", "end": "2022-08-31"},
        "research_windows": copy.deepcopy(WINDOWS),
        "data_sources": [{"normalized_dataset": "clean_daily_bar"}],
        "local_input_paths": copy.deepcopy(fixture["local_inputs"]),
        "data_api_resolution": projection,
        "step4_data_contract": copy.deepcopy(fixture["step4_contract"]),
        "daily_filter_policy": {
            "drop_suspended": True,
            "drop_limit_events": True,
        },
    }
    project_pre_release_data_access(prep, WINDOWS)
    qcfg = {
        "data_api_resolution": copy.deepcopy(prep["data_api_resolution"]),
        "step4_data_contract": copy.deepcopy(prep["step4_data_contract"]),
    }
    handoff = {
        "step3a_ready": True,
        "step3b_ready": False,
        "step4_data_contract": copy.deepcopy(prep["step4_data_contract"]),
    }
    validate = _load_script(
        "validate_step3_r5_composition",
        "skills/factor-forge-step3/scripts/validate_step3.py",
    )
    monkeypatch.setattr(validate, "WORKSPACE", fixture["workspace"])
    monkeypatch.setattr(
        validate,
        "resolve_evo_pre_release_research_windows",
        lambda **_kwargs: copy.deepcopy(WINDOWS),
    )
    monkeypatch.setattr(validate, "default_catalog_path", lambda: fixture["catalog"])
    validate.validate_step3_readiness_contract(
        prep,
        qcfg,
        {},
        handoff,
        workspace=fixture["workspace"],
        factorforge_root=fixture["factorforge"],
        fsm=FSM,
    )
    validate.validate_derived_field_contract(
        prep["local_input_paths"],
        ["close", "low", "vol"],
    )
    validate.validate_daily_io_contract(prep["local_input_paths"])


def test_qlib_contract_binding_rejects_stale_pre_projection_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    projection = _build(fixture)
    prep = {
        "report_id": REPORT,
        "factor_id": FACTOR,
        "feasibility": "ready",
        "research_windows": copy.deepcopy(WINDOWS),
        "local_input_paths": copy.deepcopy(fixture["local_inputs"]),
        "data_api_resolution": projection,
        "step4_data_contract": copy.deepcopy(fixture["step4_contract"]),
        "daily_filter_policy": {
            "drop_suspended": True,
            "drop_limit_events": True,
        },
    }
    project_pre_release_data_access(prep, WINDOWS)
    qcfg = {
        "data_api_resolution": {"clean_daily_bar": {"status": "ready"}},
        "step4_data_contract": copy.deepcopy(prep["step4_data_contract"]),
    }
    validate = _load_script(
        "validate_step3_r5_qlib_negative",
        "skills/factor-forge-step3/scripts/validate_step3.py",
    )
    monkeypatch.setattr(
        validate,
        "resolve_evo_pre_release_research_windows",
        lambda **_kwargs: copy.deepcopy(WINDOWS),
    )
    monkeypatch.setattr(validate, "default_catalog_path", lambda: fixture["catalog"])
    with pytest.raises(AssertionError, match="qlib.data_api_resolution_binding"):
        validate.validate_step3_readiness_contract(
            prep,
            qcfg,
            {},
            {"step3a_ready": True},
            workspace=fixture["workspace"],
            factorforge_root=fixture["factorforge"],
            fsm=FSM,
        )
