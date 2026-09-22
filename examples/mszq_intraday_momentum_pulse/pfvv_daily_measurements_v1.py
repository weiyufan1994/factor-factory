"""Explicit raw-minute to PF/VV daily measurements; no rolling score or returns.

This is a research preparation producer, not a Step4 raw-minute fallback. It
uses only the frozen source kernel, and publishes a new isolated directory.
09:30 boundary records and non SH/SZ A-share records are explicitly excluded
and counted. Missing observations remain missing; the market cross-section is
the observed source universe, not an inferred historical membership universe.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

_PATH = Path(__file__).with_name("pfvv_source_baseline_partitioned_v1.py")
_SPEC = importlib.util.spec_from_file_location("pfvv_daily_stream", _PATH)
_STREAM = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_STREAM)
_ADAPTER, _KERNEL = _STREAM._ADAPTER, _STREAM._KERNEL
SOURCE_PREFIX = "tushares/分钟数据/raw/stk_mins_1min/"
SOURCE_BUCKET = "yufan-data-lake"
MAX_SOURCE_BYTES = 128 * 1024**2
MAX_ARROW_COLUMN_BYTES = 256 * 1024**2


def _source_timestamps(raw, day):
    timestamps = pd.to_datetime(raw["trade_time"], errors="raise")
    if timestamps.dt.tz is not None or not timestamps.dt.normalize().eq(day).all():
        raise ValueError("source_timestamp_outside_requested_day")
    if "trade_date" in raw:
        dates = _ADAPTER._as_date_series(raw.trade_date, "source_trade_date")
        if not dates.eq(day).all():
            raise ValueError("source_date_mismatch")
    return timestamps


def _prepare_source(raw, trade_date, *, normalized_minute=None):
    from factorforge_data_api.delivery import normalize_minutes
    day = _ADAPTER._calendar_from([trade_date], "requested_date")[0]
    if raw.empty or raw.columns.duplicated().any():
        raise ValueError("empty_or_duplicate_column_minute_source")
    if normalized_minute is not None:
        if normalized_minute.frame is not raw:
            raise ValueError("normalized_minute_frame_identity_mismatch")
        frame, slots, exact = raw, normalized_minute.slots, normalized_minute.exact
        quality = normalized_minute.quality
    else:
        frame = raw
        aliases = {alias: canonical for canonical, alias in (("trade_time", "datetime"), ("vol", "volume"))
                   if canonical not in frame and alias in frame}
        if aliases:
            frame = frame.rename(columns=aliases)
        if "trade_date" not in frame:
            frame = frame.assign(trade_date=day.strftime("%Y%m%d"))
        try:
            frame, slots, exact, _, quality = normalize_minutes(frame)
        except Exception as exc:
            raise ValueError(f"invalid_minute_source: {exc}") from exc
    times = frame.trade_time
    if times.dt.tz is not None or not times.dt.normalize().eq(day).all():
        raise ValueError("source_timestamp_outside_requested_day")
    if quality['timestamp_date_mismatch_rows'] or set(frame.trade_date.unique()) != {day.strftime("%Y%m%d")}:
        raise ValueError("source_date_mismatch")
    unique = pd.Series(frame.ts_code.unique(), dtype='string')
    allowed_codes = unique[unique.str.fullmatch(r"(?:[03]\d{5}\.SZ|6\d{5}\.SH)").fillna(False)]
    allowed = frame.ts_code.isin(allowed_codes).to_numpy()
    boundary = (slots == 570) & exact
    return {"frame": frame, "day": day, "slots": slots, "exact": exact, "allowed": allowed, "boundary": boundary}


def compute_daily_measurements(raw: pd.DataFrame, trade_date: str):
    return _daily_measurements(_prepare_source(raw, trade_date))


def _daily_measurements(prepared):
    frame, day = prepared['frame'], prepared['day']
    a_share, boundary = prepared['allowed'], prepared['boundary']
    keep = a_share & ~boundary
    selected = frame.loc[keep]
    slots, exact = prepared['slots'][keep], prepared['exact'][keep]
    canonical = (((slots >= 571) & (slots <= 690)) | ((slots >= 781) & (slots <= 900))) & exact
    if selected.empty or not canonical.all():
        raise ValueError("minute_df trade_time must be real canonical 09:31-11:30/13:01-15:00 minute timestamps")
    if selected.duplicated(['ts_code', 'trade_time']).any():
        raise ValueError("minute_df contains duplicate ts_code/trade_time rows")
    validated = selected.loc[:, list(_ADAPTER.REQUIRED_MINUTE_COLUMNS)].copy()
    validated['_trade_time'] = selected.trade_time
    validated['_trade_date'] = day
    codes = pd.Index(validated.ts_code.drop_duplicates(), name='ts_code')
    _STREAM._assert_day_budget(calendar_days=1, raw_rows=len(validated), ticker_count=len(codes),
        max_calendar_days=3000, max_raw_rows_per_day=2_400_000,
        max_tickers_per_day=10_000, max_estimated_bytes_per_day=512 * 1024**2)
    close, opening, volume = _ADAPTER._one_day_panels(validated, day, codes)
    minute_returns = _KERNEL.minute_returns(close, opening)
    pf = _KERNEL.pf_daily(minute_returns, expected_slots=240)
    vv = _KERNEL.vv_daily(minute_returns, volume, expected_slots=240)
    output = pd.DataFrame({"ts_code": codes.astype(str), "trade_date": day.strftime("%Y%m%d"),
        "pf_daily": pf["daily"].reindex(codes).to_numpy(),
        "vv_daily": vv["daily"].reindex(codes).to_numpy()})
    facts = {"trade_date": day.strftime("%Y%m%d"), "source_rows": len(frame),
        "excluded_non_sh_sz_a_rows": int((~a_share).sum()),
        "excluded_0930_boundary_rows": int((a_share & boundary).sum()),
        "retained_minute_rows": len(validated), "observed_stocks": len(codes),
        "finite_pf_stocks": int(np.isfinite(output.pf_daily).sum()),
        "finite_vv_stocks": int(np.isfinite(output.vv_daily).sum()),
        "pf_zero_stocks": int(output.pf_daily.eq(0).sum()),
        "pf_selected_minutes": pf["diagnostics"]["selected_minute_count"],
        "pf_cross_section_gate_available": pf["diagnostics"]["cross_section_gate_available"],
        "missing_filled": False, "pit_membership_inferred": False}
    return output, facts


def validate_plan(plan: dict):
    if set(plan) != {"version", "trading_calendar", "source_bucket", "source_prefix", "research_id"}:
        raise ValueError("unexpected_source_plan_fields")
    if plan["version"] != "pfvv_daily_source_plan_v1":
        raise ValueError("source_plan_version")
    if plan["source_bucket"] != SOURCE_BUCKET or plan["source_prefix"] != SOURCE_PREFIX:
        raise ValueError("source_route_mismatch")
    calendar = _ADAPTER._calendar_from(plan["trading_calendar"], "source_plan_calendar")
    if len(calendar) > 3000 or not isinstance(plan["research_id"], str) or not plan["research_id"]:
        raise ValueError("source_plan_budget_or_identity")
    return calendar.strftime("%Y%m%d").tolist()


def execution_vwap(raw: pd.DataFrame, trade_date: str):
    """Frozen raw amount/vol and exact 16-bar execution-window semantics."""
    return _execution_vwap(_prepare_source(raw, trade_date))


def _execution_vwap(prepared):
    raw, day, allowed = prepared['frame'], prepared['day'], prepared['allowed']
    slots, exact = prepared['slots'], prepared['exact']
    codes = pd.Index(sorted(raw.loc[allowed, 'ts_code'].unique()), name='ts_code')
    in_window = ((slots >= 585) & (slots < 600)) | ((slots == 600) & exact)
    keep = allowed & in_window
    selected = raw.loc[keep].copy()
    selected['_clock'] = slots[keep]
    if not exact[keep].all():
        raise ValueError("execution_bar_not_on_canonical_minute")
    if selected.duplicated(['ts_code', '_clock']).any():
        raise ValueError("duplicate_execution_bar")
    for name in ["amount", "vol", "low", "high"]:
        selected[name] = pd.to_numeric(selected[name], errors="coerce")
    selected["_valid"] = (np.isfinite(selected[["amount", "vol", "low", "high"]]).all(axis=1)
        & selected.amount.ge(0) & selected.vol.ge(0) & selected.low.gt(0) & selected.high.ge(selected.low))
    grouped = selected.groupby("ts_code")
    counts = grouped.size().reindex(codes, fill_value=0)
    volume = grouped.vol.sum(min_count=1).reindex(codes)
    price = grouped.amount.sum(min_count=1).reindex(codes) / volume.where(volume.gt(0))
    valid = counts.eq(16) & grouped._valid.all().reindex(codes, fill_value=False) & price.gt(0)
    low, high = grouped.low.min().reindex(codes), grouped.high.max().reindex(codes)
    range_mismatch = valid & ((price < low * (1 - 1e-4)) | (price > high * (1 + 1e-4)))
    reason = pd.Series("MISSING_OR_INVALID_16_BAR_WINDOW", index=codes)
    reason.loc[valid] = "AVAILABLE"
    reason.loc[range_mismatch] = "AMOUNT_VOLUME_PRICE_RANGE_MISMATCH"
    valid &= ~range_mismatch
    return pd.DataFrame({"ts_code": codes, "trade_date": day.strftime("%Y%m%d"),
        "vwap_0945_1000_unadjusted": price.where(valid).to_numpy(),
        "execution_bar_count": counts.to_numpy(), "price_basis": "UNADJUSTED_AMOUNT_OVER_VOL",
        "execution_price_status": reason.to_numpy()})


def compute_daily_bundle(raw, trade_date, *, normalized_minute=None):
    """Normalize/validate identities once and reuse the shared SDK context."""
    prepared = _prepare_source(raw, trade_date, normalized_minute=normalized_minute)
    measurements, facts = _daily_measurements(prepared)
    prices = _execution_vwap(prepared)
    facts['execution_price_status_counts'] = prices.execution_price_status.value_counts().to_dict()
    return measurements, prices, facts


def materialize(plan: dict, output_root: Path, read_source):
    """One read per explicit day; failure preserves partial, never resumes."""
    import pyarrow.parquet as pq
    days = validate_plan(plan)
    root = Path(output_root)
    if not root.is_absolute() or root.exists() or not root.parent.is_dir():
        raise ValueError("output_must_be_new_absolute_child_of_existing_parent")
    if root.parent.resolve() != root.parent or ".." in root.parts:
        raise ValueError("output_parent_must_be_resolved_without_alias")
    root.mkdir(exist_ok=False)
    def write_json(name, value):
        with (root / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    write_json("source_plan.json", plan)
    rows = []
    try:
        for day in days:
            key = f"{SOURCE_PREFIX}trade_date={day}/part-000.parquet"
            raw, identity = read_source(SOURCE_BUCKET, key, MAX_SOURCE_BYTES)
            if not 0 < len(raw) <= MAX_SOURCE_BYTES:
                raise ValueError("source_byte_budget")
            parquet = pq.ParquetFile(io.BytesIO(raw))
            if parquet.metadata.num_rows > 2_400_000:
                raise ValueError("source_row_budget")
            columns = [c for c in ["ts_code", "trade_date", "trade_time", "datetime", "open", "close", "low", "high", "amount", "vol", "volume"]
                       if c in parquet.schema_arrow.names]
            # Refuse a compressed expansion before Arrow allocation. This is
            # a selected-column budget, not a claim about process peak RSS.
            column_indices = [parquet.schema_arrow.names.index(c) for c in columns]
            decoded_bytes = sum(parquet.metadata.row_group(g).column(c).total_uncompressed_size
                for g in range(parquet.metadata.num_row_groups) for c in column_indices)
            if decoded_bytes > MAX_ARROW_COLUMN_BYTES:
                raise ValueError("source_arrow_decompression_budget")
            frame = parquet.read(columns=columns).to_pandas()
            output, prices, facts = compute_daily_bundle(frame, day)
            facts["execution_price_status_counts"] = prices.execution_price_status.value_counts().to_dict()
            path = root / f"daily_{day}.parquet"
            with path.open("xb") as stream:
                output.to_parquet(stream, index=False)
            price_path = root / f"execution_{day}.parquet"
            with price_path.open("xb") as stream:
                prices.to_parquet(stream, index=False)
            rows.append({"trade_date": day, "path": path.name, "rows": len(output),
                "execution_path": price_path.name, "execution_sha256": hashlib.sha256(price_path.read_bytes()).hexdigest(),
                "source_uri": f"s3://{SOURCE_BUCKET}/{key}", "source_bytes": len(raw),
                "source_sha256": hashlib.sha256(raw).hexdigest(), "source_identity": identity,
                "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "coverage": facts})
            print(json.dumps({"phase": "DAILY_MEASUREMENT_WRITTEN", **facts}), flush=True)
        result = {"version": "pfvv_daily_measurements_manifest_v1", "status": "COMPLETE",
            "research_id": plan["research_id"], "trading_calendar": days, "days": rows,
            "columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
            "domain": "OBSERVED_SH_SZ_A_SHARE_MINUTE_CROSS_SECTION",
            "vv_cs_standardized": False, "rolling_applied": False,
            "pfvv_prepared_daily_state": {"contract_version": "pfvv_prepared_daily_state_v1",
                "measurement_authority": "pfvv_source_baseline_v1", "calendar_dates": days,
                "day_paths": {row["trade_date"]: row["path"] for row in rows},
                "required_columns": ["ts_code", "trade_date", "pf_daily", "vv_daily"]},
            "factor_returns_evaluated": False, "oos_accessed": False}
        write_json("daily_measurements_manifest.json", result)
        return result
    except Exception as error:
        write_json("partial_failure.json", {"status": "PARTIAL_NOT_REUSABLE", "completed_days": rows,
            "failed_date": days[len(rows)] if len(rows) < len(days) else None,
            "error": f"{type(error).__name__}: {error}", "auto_retry": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-plan", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--catalog-sha256", required=True)
    parser.add_argument("--cache-root")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=2048)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prewarm", action="store_true")
    parser.add_argument("--source-mode", choices=['ttl_snapshot', 'latest', 'pinned'], default='ttl_snapshot')
    parser.add_argument("--object-sha256-manifest")
    parser.add_argument("--calendar-identity")
    args = parser.parse_args()
    plan = json.loads(Path(args.source_plan).read_text())
    validate_plan(plan)
    from factorforge_data_api import DataApiClient
    from factorforge_data_api.runtime import ReadPolicy
    from factor_factory.pfvv_preparation import materialize_sdk
    policy = ReadPolicy(cache_mode='on', cache_root=args.cache_root, source_mode=args.source_mode,
        object_sha256=json.loads(Path(args.object_sha256_manifest).read_text()) if args.object_sha256_manifest else {})
    client = DataApiClient.from_catalog(args.catalog, expected_sha256=args.catalog_sha256, read_policy=policy)
    result = materialize_sdk(plan, Path(args.output_root), client, producer_path=__file__,
        workers=args.workers, memory_budget_bytes=args.memory_budget_mb*1024**2,
        resume=args.resume, prewarm=args.prewarm, calendar_identity=args.calendar_identity)
    print(json.dumps({'status': result['status'], 'days': len(result['days']), 'performance': result['performance']}))


if __name__ == "__main__":
    main()
