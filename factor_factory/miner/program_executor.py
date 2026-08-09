from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from factor_factory.miner.candidates import validate_candidate_packet
from factor_factory.miner.common import utc_now, workspace_path, write_json
from factor_factory.miner.data_split import (
    CANONICAL_DATA_SPLIT_REF,
    validate_data_split_reference,
)
from factor_factory.research_evidence import sha256_file


BLOCK_PROGRAM_CONTRACT_INVALID = "BLOCK_FACTORFORGE_MINER_PROGRAM_CONTRACT_INVALID"
BLOCK_PROGRAM_EXECUTION_UNSUPPORTED = "BLOCK_FACTORFORGE_MINER_PROGRAM_EXECUTION_UNSUPPORTED"
BLOCK_PROGRAM_INPUT_INVALID = "BLOCK_FACTORFORGE_MINER_PROGRAM_INPUT_INVALID"
BLOCK_PROGRAM_LINEAGE_INVALID = (
    "BLOCK_FACTORFORGE_MINER_PROGRAM_EXECUTION_LINEAGE_INVALID"
)


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _load_panel(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"{BLOCK_PROGRAM_INPUT_INVALID}:unsupported_format:{path.suffix}")


def _daily_last(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.sort_values(["ts_code", "trade_date"])
        .groupby(["trade_date", "ts_code"], as_index=False)
        .last()
    )


def _daily_intraday_aggregate(
    frame: pd.DataFrame,
    values: pd.Series,
    *,
    aggregation: str,
) -> pd.DataFrame:
    work = frame[["trade_date", "ts_code"]].copy()
    work["_value"] = values
    grouped = work.groupby(["trade_date", "ts_code"])["_value"]
    if aggregation == "sum":
        out = grouped.sum(min_count=1)
    elif aggregation == "mean":
        out = grouped.mean()
    elif aggregation == "skew":
        out = grouped.skew()
    else:
        out = grouped.apply(lambda value: value.kurt())
    return out.rename("factor_value").reset_index()


def _turnover_acceleration(frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
    daily = _daily_last(frame)
    lookback = int(parameters.get("lookback") or 5)
    grouped = daily.groupby("ts_code", sort=False)["turnover"]
    baseline = grouped.transform(
        lambda values: values.shift(1).rolling(lookback, min_periods=1).mean()
    )
    daily["factor_value"] = daily["turnover"] - baseline
    return daily[["trade_date", "ts_code", "factor_value"]]


def _open_close(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    daily = _daily_last(frame)
    daily["factor_value"] = (
        daily["close"].astype(float) - daily["open"].astype(float)
    ) / daily["open"].replace(0, np.nan).astype(float)
    return daily[["trade_date", "ts_code", "factor_value"]]


def _minute_returns(frame: pd.DataFrame) -> pd.Series:
    sort_fields = ["ts_code", "trade_date"]
    if "trade_time" in frame:
        sort_fields.append("trade_time")
    ordered = frame.sort_values(sort_fields)
    return ordered.groupby(["ts_code", "trade_date"], sort=False)["close"].pct_change()


def _intraday_skew(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["ts_code", "trade_date"] + (["trade_time"] if "trade_time" in frame else [])
    )
    return _daily_intraday_aggregate(
        ordered,
        _minute_returns(ordered),
        aggregation="skew",
    )


def _intraday_kurtosis(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["ts_code", "trade_date"] + (["trade_time"] if "trade_time" in frame else [])
    )
    return _daily_intraday_aggregate(
        ordered,
        _minute_returns(ordered),
        aggregation="kurtosis",
    )


def _realized_var_over_range(frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
    floor = float(parameters.get("range_floor") or 1e-6)
    ordered = frame.sort_values(
        ["ts_code", "trade_date"] + (["trade_time"] if "trade_time" in frame else [])
    )
    returns = _minute_returns(ordered)
    work = ordered[["trade_date", "ts_code", "high", "low", "close"]].copy()
    work["_ret2"] = returns * returns
    grouped = work.groupby(["trade_date", "ts_code"])
    daily = grouped.agg(
        realized_var=("_ret2", "sum"),
        high=("high", "max"),
        low=("low", "min"),
        anchor=("close", "first"),
    ).reset_index()
    normalized_range = (
        (daily["high"] - daily["low"]) / daily["anchor"].replace(0, np.nan)
    ).abs()
    daily["factor_value"] = daily["realized_var"] / np.maximum(
        normalized_range * normalized_range,
        floor,
    )
    return daily[["trade_date", "ts_code", "factor_value"]]


def _volume_weighted_range(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    work = frame[["trade_date", "ts_code", "high", "low", "close", "vol"]].copy()
    work["_weighted"] = (
        (work["high"] - work["low"]) / work["close"].replace(0, np.nan)
    ) * work["vol"]
    grouped = work.groupby(["trade_date", "ts_code"])
    daily = grouped.agg(weighted=("_weighted", "sum"), volume=("vol", "sum")).reset_index()
    daily["factor_value"] = daily["weighted"] / daily["volume"].replace(0, np.nan)
    return daily[["trade_date", "ts_code", "factor_value"]]


def _location_pressure(
    frame: pd.DataFrame,
    parameters: dict[str, Any],
) -> pd.DataFrame:
    work = frame[["trade_date", "ts_code", "high", "low", "close", "vol"]].copy()
    span = (work["high"] - work["low"]).replace(0, np.nan)
    location = (work["close"] - work["low"]) / span
    if parameters.get("location") == "low":
        location = 1.0 - location
    work["_weighted"] = location * work["vol"]
    grouped = work.groupby(["trade_date", "ts_code"])
    daily = grouped.agg(weighted=("_weighted", "sum"), volume=("vol", "sum")).reset_index()
    daily["factor_value"] = daily["weighted"] / daily["volume"].replace(0, np.nan)
    return daily[["trade_date", "ts_code", "factor_value"]]


def _signed_volume(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    work = frame[["trade_date", "ts_code", "open", "close", "vol"]].copy()
    work["_signed"] = np.sign(work["close"] - work["open"]) * work["vol"]
    grouped = work.groupby(["trade_date", "ts_code"])
    daily = grouped.agg(signed=("_signed", "sum"), volume=("vol", "sum")).reset_index()
    daily["factor_value"] = daily["signed"] / daily["volume"].replace(0, np.nan)
    return daily[["trade_date", "ts_code", "factor_value"]]


def _flow_state(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    daily = _daily_last(frame)
    daily["factor_value"] = daily["flow_z"].astype(float) + daily[
        "large_flow_z"
    ].astype(float)
    return daily[["trade_date", "ts_code", "factor_value"]]


def _value_occupation(frame: pd.DataFrame, _: dict[str, Any]) -> pd.DataFrame:
    daily = _daily_last(frame)
    daily["factor_value"] = -daily["poc_distance"].abs().astype(float) + daily[
        "value_area_position"
    ].astype(float)
    return daily[["trade_date", "ts_code", "factor_value"]]


PROGRAMS: dict[str, Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]] = {
    "turnover_acceleration": _turnover_acceleration,
    "open_gap_intraday_continuation": _open_close,
    "intraday_return_skew": _intraday_skew,
    "intraday_return_kurtosis": _intraday_kurtosis,
    "realized_var_over_range": _realized_var_over_range,
    "volume_weighted_range": _volume_weighted_range,
    "high_location_volume_pressure": _location_pressure,
    "low_location_absorption": _location_pressure,
    "up_down_volume_imbalance_proxy": _signed_volume,
    "cutoff_flow_persistence": _flow_state,
    "value_occupation_support_overhang": _value_occupation,
}


def _postprocess_factor(
    factor: pd.DataFrame,
    source: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    parameters = dict(contract.get("parameters") or {})
    if parameters.get("ablation") == "identity_raw_field":
        raw_field = next(
            (
                field
                for field in contract.get("required_fields") or []
                if field not in {"trade_date", "ts_code"}
            ),
            None,
        )
        if raw_field and raw_field in source:
            factor = _daily_last(source)[
                ["trade_date", "ts_code", raw_field]
            ].rename(columns={raw_field: "factor_value"})
    if parameters.get("null_control") == "lag_one_period":
        factor = factor.sort_values(["ts_code", "trade_date"])
        factor["factor_value"] = factor.groupby("ts_code", sort=False)[
            "factor_value"
        ].shift(1)
    normalization = parameters.get("normalization")
    if normalization == "cross_sectional_rank":
        factor["factor_value"] = factor.groupby("trade_date")["factor_value"].rank(
            pct=True
        )
    elif normalization == "cross_sectional_zscore":
        grouped = factor.groupby("trade_date")["factor_value"]
        mean_value = grouped.transform("mean")
        std_value = grouped.transform("std").replace(0, np.nan)
        factor["factor_value"] = (factor["factor_value"] - mean_value) / std_value
    return factor


def _validate_program_contract(packet: dict[str, Any]) -> dict[str, Any]:
    contract = packet.get("candidate_program_contract")
    if not isinstance(contract, dict):
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:missing")
    program = {
        "language": contract.get("language"),
        "entrypoint": contract.get("entrypoint"),
        "required_fields": contract.get("required_fields") or [],
        "operator_dependencies": contract.get("operator_dependencies") or [],
        "parameters": contract.get("parameters") or {},
    }
    if contract.get("program_hash") != _stable_hash(program):
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:hash_mismatch")
    expected_column = f"factor__{packet.get('candidate_id')}"
    if contract.get("expected_factor_column") != expected_column:
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:factor_column")
    return contract


def validate_program_execution_report(
    report: Any,
    *,
    workspace_root: Path,
    candidate_manifest: dict[str, Any],
    output_panel_path: Path,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(report, dict):
        return [f"{BLOCK_PROGRAM_LINEAGE_INVALID}:report_missing"]
    if report.get("version") != "factorforge_miner_program_execution_v1":
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:version")
    if report.get("campaign_id") != candidate_manifest.get("campaign_id"):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:campaign")
    if report.get("candidate_manifest_content_sha256") != _stable_hash(
        candidate_manifest
    ):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:candidate_manifest")
    root = workspace_root.expanduser().resolve(strict=False)
    expected_output = output_panel_path.expanduser().resolve(strict=False)
    reported_output = Path(
        str(report.get("output_panel_path") or "")
    ).expanduser().resolve(strict=False)
    if (
        reported_output != expected_output
        or (reported_output != root and root not in reported_output.parents)
    ):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:output_path")
        return reasons
    if not reported_output.is_file():
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:output_missing")
        return reasons
    if report.get("output_panel_sha256") != sha256_file(reported_output):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:output_hash")
    source_path = Path(
        str(report.get("source_panel_path") or "")
    ).expanduser().resolve(strict=False)
    if source_path != root and root not in source_path.parents:
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:source_path")
        return reasons
    if not source_path.is_file():
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:source_missing")
        return reasons
    if report.get("source_panel_sha256") != sha256_file(source_path):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:source_hash")
        return reasons
    split_reasons = validate_data_split_reference(
        workspace_root=root,
        manifest_ref=report.get("data_split_manifest_ref"),
        manifest_sha256=report.get("data_split_manifest_sha256"),
        expected_campaign_id=str(candidate_manifest.get("campaign_id") or ""),
        expected_is_panel_sha256=str(
            report.get("source_panel_sha256") or ""
        ),
        expected_selection_window_id=report.get("selection_window_id"),
        expected_universe_id=report.get("universe_id"),
    )
    if split_reasons:
        reasons.extend(
            f"{BLOCK_PROGRAM_LINEAGE_INVALID}:data_split:{reason}"
            for reason in split_reasons
        )
        return list(dict.fromkeys(reasons))
    if (
        candidate_manifest.get("data_split_manifest_ref")
        != report.get("data_split_manifest_ref")
        or candidate_manifest.get("data_split_manifest_sha256")
        != report.get("data_split_manifest_sha256")
        or any(
            packet.get("data_split_manifest_ref")
            != report.get("data_split_manifest_ref")
            or packet.get("data_split_manifest_sha256")
            != report.get("data_split_manifest_sha256")
            for packet in candidate_manifest.get("candidates") or []
            if isinstance(packet, dict)
        )
    ):
        reasons.append(
            f"{BLOCK_PROGRAM_LINEAGE_INVALID}:data_split_binding"
        )
        return list(dict.fromkeys(reasons))
    if report.get("candidate_specific_columns_only") is not True:
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:column_policy")

    source = _load_panel(source_path)
    actual = _load_panel(reported_output)
    identity_columns = ["trade_date", "ts_code"]
    passthrough = [
        column
        for column in ("forward_return", "turnover")
        if column in source.columns
    ]
    expected_columns = {*identity_columns, *passthrough}
    expected_base = (
        source[[*identity_columns, *passthrough]]
        .groupby(identity_columns, as_index=False)
        .last()
        .sort_values(identity_columns)
        .reset_index(drop=True)
    )
    if not set(expected_base.columns).issubset(actual.columns):
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:base_columns")
    else:
        actual_base = (
            actual[list(expected_base.columns)]
            .sort_values(identity_columns)
            .reset_index(drop=True)
        )
        if (
            expected_base[identity_columns].astype(str).to_dict("records")
            != actual_base[identity_columns].astype(str).to_dict("records")
        ):
            reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:base_identity")
        for column in passthrough:
            expected_values = pd.to_numeric(
                expected_base[column], errors="coerce"
            ).to_numpy(dtype=float)
            actual_values = pd.to_numeric(
                actual_base[column], errors="coerce"
            ).to_numpy(dtype=float)
            if not np.allclose(
                expected_values,
                actual_values,
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
            ):
                reasons.append(
                    f"{BLOCK_PROGRAM_LINEAGE_INVALID}:base_values:{column}"
                )
    execution_rows = {
        str(row.get("candidate_id")): row
        for row in report.get("executions") or []
        if isinstance(row, dict) and row.get("candidate_id")
    }
    expected_hashes: set[str] = set()
    for packet in candidate_manifest.get("candidates") or []:
        if not isinstance(packet, dict) or packet.get("dependency_status") != "ready":
            continue
        candidate_id = str(packet.get("candidate_id") or "")
        try:
            contract = _validate_program_contract(packet)
        except ValueError as exc:
            reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:{exc}")
            continue
        program_hash = str(contract.get("program_hash") or "")
        expected_hashes.add(program_hash)
        factor_column = str(contract.get("expected_factor_column") or "")
        expected_columns.add(factor_column)
        execution = execution_rows.get(candidate_id)
        if (
            not isinstance(execution, dict)
            or execution.get("status") != "executed"
            or execution.get("program_hash") != program_hash
            or execution.get("factor_column") != factor_column
        ):
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:execution_binding:{candidate_id}"
            )
            continue
        executor = PROGRAMS.get(str(contract.get("entrypoint") or ""))
        if executor is None:
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:executor:{candidate_id}"
            )
            continue
        missing = sorted(
            set(str(field) for field in contract.get("required_fields") or [])
            - set(str(column) for column in source.columns)
        )
        if missing:
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:source_fields:{candidate_id}"
            )
            continue
        expected_factor = executor(
            source.copy(), dict(contract.get("parameters") or {})
        )
        expected_factor = _postprocess_factor(
            expected_factor, source, contract
        ).rename(columns={"factor_value": factor_column})
        expected_factor = expected_factor[
            [*identity_columns, factor_column]
        ].sort_values(identity_columns).reset_index(drop=True)
        if factor_column not in actual.columns:
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:factor_missing:{candidate_id}"
            )
            continue
        actual_factor = actual[
            [*identity_columns, factor_column]
        ].sort_values(identity_columns).reset_index(drop=True)
        if (
            expected_factor[identity_columns].astype(str).to_dict("records")
            != actual_factor[identity_columns].astype(str).to_dict("records")
        ):
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:factor_identity:{candidate_id}"
            )
            continue
        expected_values = pd.to_numeric(
            expected_factor[factor_column], errors="coerce"
        ).to_numpy(dtype=float)
        actual_values = pd.to_numeric(
            actual_factor[factor_column], errors="coerce"
        ).to_numpy(dtype=float)
        if not np.allclose(
            expected_values,
            actual_values,
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        ):
            reasons.append(
                f"{BLOCK_PROGRAM_LINEAGE_INVALID}:factor_values:{candidate_id}"
            )
    actual_hashes = {
        str(value)
        for value in report.get("executed_program_hashes") or []
        if isinstance(value, str)
    }
    if actual_hashes != expected_hashes:
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:program_hashes")
    if set(actual.columns) != expected_columns:
        reasons.append(f"{BLOCK_PROGRAM_LINEAGE_INVALID}:unexpected_columns")
    return list(dict.fromkeys(reasons))


def execute_candidate_programs(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidate_manifest: dict[str, Any],
    source_panel_path: Path,
    data_split_manifest_path: Path,
    artifact_tag: str = "g00",
) -> dict[str, Any]:
    workspace = workspace_root.expanduser().resolve(strict=False)
    resolved_source = source_panel_path.expanduser().resolve(strict=False)
    if resolved_source != workspace and workspace not in resolved_source.parents:
        raise ValueError(f"{BLOCK_PROGRAM_INPUT_INVALID}:source_outside_workspace")
    if not resolved_source.is_file():
        raise ValueError(f"{BLOCK_PROGRAM_INPUT_INVALID}:source_missing")
    resolved_split = data_split_manifest_path.expanduser().resolve(strict=False)
    expected_split = (workspace / CANONICAL_DATA_SPLIT_REF).resolve(
        strict=False
    )
    if resolved_split != expected_split:
        raise ValueError(
            f"{BLOCK_PROGRAM_INPUT_INVALID}:"
            "data_split_manifest_not_canonical"
        )
    split_reasons = validate_data_split_reference(
        workspace_root=workspace,
        manifest_ref=CANONICAL_DATA_SPLIT_REF,
        manifest_sha256=(
            sha256_file(resolved_split) if resolved_split.is_file() else None
        ),
        expected_campaign_id=campaign_id,
        expected_is_panel_sha256=sha256_file(resolved_source),
    )
    if split_reasons:
        raise ValueError(
            f"{BLOCK_PROGRAM_INPUT_INVALID}:data_split:"
            + ";".join(split_reasons)
        )
    split_manifest = json.loads(resolved_split.read_text(encoding="utf-8"))
    split_is = (
        split_manifest.get("is_search")
        if isinstance(split_manifest.get("is_search"), dict)
        else {}
    )
    if (
        candidate_manifest.get("data_split_manifest_ref")
        != CANONICAL_DATA_SPLIT_REF
        or candidate_manifest.get("data_split_manifest_sha256")
        != sha256_file(resolved_split)
        or any(
            packet.get("data_split_manifest_ref")
            != CANONICAL_DATA_SPLIT_REF
            or packet.get("data_split_manifest_sha256")
            != sha256_file(resolved_split)
            for packet in candidate_manifest.get("candidates") or []
            if isinstance(packet, dict)
        )
    ):
        raise ValueError(
            f"{BLOCK_PROGRAM_CONTRACT_INVALID}:data_split_binding"
        )
    if candidate_manifest.get("campaign_id") != campaign_id:
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:campaign_mismatch")
    candidate_ids: list[str] = []
    ready_program_hashes: list[str] = []
    for packet in candidate_manifest.get("candidates") or []:
        if not isinstance(packet, dict):
            raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:candidate_packet")
        validate_candidate_packet(packet)
        if packet.get("campaign_id") != campaign_id:
            raise ValueError(
                f"{BLOCK_PROGRAM_CONTRACT_INVALID}:candidate_campaign_mismatch"
            )
        candidate_ids.append(str(packet.get("candidate_id") or ""))
        if packet.get("dependency_status") == "ready":
            ready_program_hashes.append(
                str(
                    (packet.get("candidate_program_contract") or {}).get(
                        "program_hash"
                    )
                    or ""
                )
            )
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:candidate_id_duplicate")
    if len(ready_program_hashes) != len(set(ready_program_hashes)):
        raise ValueError(f"{BLOCK_PROGRAM_CONTRACT_INVALID}:program_hash_duplicate")
    source = _load_panel(resolved_source)
    required_identity = {"trade_date", "ts_code"}
    if not required_identity.issubset(source.columns):
        raise ValueError(f"{BLOCK_PROGRAM_INPUT_INVALID}:identity_columns")
    passthrough = [
        column
        for column in ("forward_return", "turnover")
        if column in source.columns
    ]
    output = (
        source[["trade_date", "ts_code", *passthrough]]
        .groupby(["trade_date", "ts_code"], as_index=False)
        .last()
    )
    executions: list[dict[str, Any]] = []
    for packet in candidate_manifest.get("candidates") or []:
        if not isinstance(packet, dict) or packet.get("dependency_status") != "ready":
            continue
        candidate_id = str(packet.get("candidate_id") or "")
        contract = _validate_program_contract(packet)
        entrypoint = str(contract.get("entrypoint") or "")
        missing = sorted(
            set(str(field) for field in contract.get("required_fields") or [])
            - set(str(column) for column in source.columns)
        )
        if missing:
            executions.append(
                {
                    "candidate_id": candidate_id,
                    "program_hash": contract.get("program_hash"),
                    "status": "blocked",
                    "block_reason": f"{BLOCK_PROGRAM_INPUT_INVALID}:missing_fields:{','.join(missing)}",
                }
            )
            continue
        executor = PROGRAMS.get(entrypoint)
        if executor is None:
            executions.append(
                {
                    "candidate_id": candidate_id,
                    "program_hash": contract.get("program_hash"),
                    "status": "blocked",
                    "block_reason": f"{BLOCK_PROGRAM_EXECUTION_UNSUPPORTED}:{entrypoint}",
                }
            )
            continue
        factor = executor(source.copy(), dict(contract.get("parameters") or {}))
        factor = _postprocess_factor(factor, source, contract)
        column = str(contract["expected_factor_column"])
        factor = factor.rename(columns={"factor_value": column})
        output = output.merge(
            factor[["trade_date", "ts_code", column]],
            on=["trade_date", "ts_code"],
            how="outer",
            validate="one_to_one",
        )
        executions.append(
            {
                "candidate_id": candidate_id,
                "entrypoint": entrypoint,
                "program_hash": contract.get("program_hash"),
                "factor_column": column,
                "status": "executed",
                "non_null_count": int(factor[column].notna().sum()),
            }
        )
    output_path = workspace_path(
        workspace_root,
        "objects",
        "program_execution",
        artifact_tag,
        "candidate_signal_panel.parquet",
        campaign_id=campaign_id,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False)
    report = {
        "version": "factorforge_miner_program_execution_v1",
        "campaign_id": campaign_id,
        "generated_at_utc": utc_now(),
        "candidate_manifest_content_sha256": _stable_hash(candidate_manifest),
        "source_panel_path": str(resolved_source),
        "source_panel_sha256": sha256_file(resolved_source),
        "data_split_manifest_ref": CANONICAL_DATA_SPLIT_REF,
        "data_split_manifest_sha256": sha256_file(resolved_split),
        "selection_window_id": split_is.get("window_id"),
        "universe_id": split_manifest.get("universe_id"),
        "output_panel_path": str(output_path),
        "output_panel_sha256": sha256_file(output_path),
        "candidate_specific_columns_only": True,
        "executions": executions,
        "executed_program_hashes": [
            row["program_hash"] for row in executions if row.get("status") == "executed"
        ],
        "promotion_forbidden_until_formal": True,
    }
    write_json(
        workspace_path(
            workspace_root,
            "objects",
            "program_execution",
            artifact_tag,
            "program_execution_report.json",
            campaign_id=campaign_id,
        ),
        report,
    )
    return report
