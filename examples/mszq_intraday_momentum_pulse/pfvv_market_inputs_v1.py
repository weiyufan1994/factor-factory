"""Bounded local join of explicit daily close and adjustment-factor files."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


START, END = "20160104", "20250711"
CODE_RE = re.compile(r"(?:[03]\d{5}\.SZ|6\d{5}\.SH)\Z")
OUTPUT_COLUMNS = ["ts_code", "trade_date", "close_unadjusted", "adj_factor"]


class MarketInputsError(ValueError):
    pass


def _path(value: Any, base: Path, field: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise MarketInputsError(f"{field}_must_be_explicit_path")
    candidate = Path(value).expanduser()
    result = candidate if candidate.is_absolute() else base / candidate
    if result.is_symlink() or not result.is_file():
        raise MarketInputsError(f"{field}_missing_or_symlink:{result}")
    return result.resolve()


def _dates(series: pd.Series, field: str) -> pd.Series:
    values = series.astype("string").str.strip()
    # Keep compact producer dates and normalize ISO/date-like values without
    # silently dropping invalid rows.
    compact = values.str.replace(r"[-/]", "", regex=True)
    parsed = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    fallback = pd.to_datetime(values, errors="coerce")
    parsed = parsed.fillna(fallback)
    if parsed.isna().any():
        raise MarketInputsError(f"{field}_invalid_date")
    return parsed.dt.strftime("%Y%m%d")


def _check_range(values: pd.Series, field: str) -> None:
    if values.lt(START).any() or values.gt(END).any():
        raise MarketInputsError(f"{field}_outside_supported_window")


def _stage_once(connection: sqlite3.Connection, path: Path, *, table: str,
                value_column: str, dates: set[str], field: str,
                ignore_off_calendar_adj: bool = False) -> dict[str, Any]:
    """One source scan and a disk-backed index, even for security-clustered files."""
    import pyarrow.parquet as pq
    if table not in {"daily", "adjustments"}:
        raise MarketInputsError("internal_table_invalid")
    connection.execute(f"CREATE TABLE {table} (trade_date TEXT NOT NULL, ts_code TEXT NOT NULL, value REAL, PRIMARY KEY(trade_date, ts_code)) WITHOUT ROWID")
    counts = {"bj_rows": 0, "out_of_universe_rows": 0, "source_rows": 0,
              "off_calendar_excluded_rows": 0, "off_calendar_excluded_dates": {}}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=["trade_date", "ts_code", value_column]):
        frame = batch.to_pandas()
        counts["source_rows"] += len(frame)
        normalized = _dates(frame["trade_date"], field + ".trade_date")
        _check_range(normalized, field + ".trade_date")
        on_calendar = normalized.isin(dates)
        if not on_calendar.all() and not (table == "adjustments" and ignore_off_calendar_adj):
            raise MarketInputsError(f"{field}_date_outside_explicit_calendar")
        if not on_calendar.all():
            counts["off_calendar_excluded_rows"] += int((~on_calendar).sum())
            for day, count in normalized.loc[~on_calendar].value_counts().items():
                counts["off_calendar_excluded_dates"][day] = counts["off_calendar_excluded_dates"].get(day, 0) + int(count)
        codes = frame["ts_code"].astype("string").str.strip()
        universe = codes.str.match(CODE_RE, na=False)
        selected = universe & on_calendar
        counts["bj_rows"] += int(codes.str.endswith(".BJ", na=False).sum())
        counts["out_of_universe_rows"] += int((~universe).sum())
        values = pd.to_numeric(frame.loc[selected, value_column], errors="raise")
        if values.isin([float("inf"), float("-inf")]).any():
            raise MarketInputsError(f"{field}_nonfinite_value")
        rows = zip(normalized.loc[selected], codes.loc[selected],
                   (None if pd.isna(value) else float(value) for value in values))
        try:
            connection.executemany(f"INSERT INTO {table} VALUES (?, ?, ?)", rows)
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise MarketInputsError(f"{field}_duplicate_stock_day") from exc
    return counts


def assemble_market_inputs(*, daily_path: str | Path, adj_factor_path: str | Path, calendar_path: str | Path, output_root: str | Path, ignore_off_calendar_adj: bool = False) -> dict[str, Any]:
    """Join explicit daily/adj files by exact stock-day keys with bounded reads."""
    daily = _path(daily_path, Path.cwd(), "daily_path")
    adj = _path(adj_factor_path, Path.cwd(), "adj_factor_path")
    calendar_file = _path(calendar_path, Path.cwd(), "calendar_path")
    root = Path(output_root).expanduser()
    if not root.is_absolute() or root.exists() or not root.parent.is_dir() or root.is_symlink():
        raise MarketInputsError("output_root_must_be_new_absolute_directory")
    calendar_frame = pd.read_parquet(calendar_file)
    if "trade_date" not in calendar_frame.columns:
        raise MarketInputsError("calendar_missing_trade_date")
    calendar = _dates(calendar_frame["trade_date"], "calendar.trade_date")
    _check_range(calendar, "calendar.trade_date")
    if calendar.empty or calendar.duplicated().any() or calendar.tolist() != sorted(calendar.tolist()):
        raise MarketInputsError("calendar_must_be_sorted_unique")
    if "is_open" in calendar_frame and not calendar_frame.is_open.astype(str).isin(["1", "True"]).all():
        raise MarketInputsError("calendar_must_contain_only_open_days")
    calendar_days = calendar.tolist()
    import pyarrow.parquet as pq
    daily_schema = set(pq.ParquetFile(daily).schema_arrow.names)
    adj_schema = set(pq.ParquetFile(adj).schema_arrow.names)
    if not {"trade_date", "ts_code", "close"}.issubset(daily_schema):
        raise MarketInputsError("daily_missing_close")
    if not {"trade_date", "ts_code", "adj_factor"}.issubset(adj_schema):
        raise MarketInputsError("adj_factor_missing_adj_factor")
    root.mkdir()
    output = root / "daily_prices.parquet"
    qa_path = root / "qa_summary.json"
    import pyarrow as pa
    scratch = root / "_join.sqlite"
    connection = sqlite3.connect(scratch)
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("PRAGMA temp_store=FILE")
    writer = None
    missing_adj = 0
    daily_missing_days = 0
    joined_rows = 0
    try:
        daily_counts = _stage_once(connection, daily, table="daily", value_column="close", dates=set(calendar_days), field="daily")
        adj_counts = _stage_once(connection, adj, table="adjustments", value_column="adj_factor", dates=set(calendar_days), field="adj_factor", ignore_off_calendar_adj=ignore_off_calendar_adj)
        daily_missing_days = len(calendar_days) - connection.execute("SELECT COUNT(DISTINCT trade_date) FROM daily").fetchone()[0]
        cursor = connection.execute("SELECT d.ts_code, d.trade_date, d.value, a.value FROM daily d LEFT JOIN adjustments a ON d.trade_date=a.trade_date AND d.ts_code=a.ts_code ORDER BY d.trade_date, d.ts_code")
        schema = pa.schema([(name, pa.string() if name in {"ts_code", "trade_date"} else pa.float64()) for name in OUTPUT_COLUMNS])
        writer = pq.ParquetWriter(output, schema)
        while rows := cursor.fetchmany(65536):
            merged = pd.DataFrame.from_records(rows, columns=OUTPUT_COLUMNS)
            missing_adj += int(merged["adj_factor"].isna().sum())
            table = pa.Table.from_pandas(merged, schema=schema, preserve_index=False)
            writer.write_table(table)
            joined_rows += len(rows)
    finally:
        if writer is not None:
            writer.close()
        connection.close()
    qa = {"version": "pfvv_market_inputs_qa_v1", "calendar_path": os.fspath(calendar_file),
          "calendar_days": len(calendar_days), "joined_rows": joined_rows, "daily_missing_days": daily_missing_days,
          "missing_adj_factor_rows": missing_adj, "daily_bj_rows": daily_counts["bj_rows"],
          "adj_factor_bj_rows": adj_counts["bj_rows"], "daily_out_of_universe_rows": daily_counts["out_of_universe_rows"],
          "adj_factor_out_of_universe_rows": adj_counts["out_of_universe_rows"], "forward_fill": False, "backfill": False,
          "join_strategy": "single_scan_disk_backed_exact_key_join", "batch_rows": 65536, "sqlite_cache_kib": 65536,
          "daily_source_rows_scanned": daily_counts["source_rows"], "adj_source_rows_scanned": adj_counts["source_rows"],
          "ignore_off_calendar_adj": ignore_off_calendar_adj,
          "off_calendar_adj_excluded_rows": adj_counts["off_calendar_excluded_rows"],
          "off_calendar_adj_excluded_dates": adj_counts["off_calendar_excluded_dates"]}
    with qa_path.open("x", encoding="utf-8") as stream:
        json.dump(qa, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    # This new directory's disposable index is retained on failure, but is not
    # part of the successful delivery. Never remove any source or old output.
    scratch.unlink()
    return {"prepared_path": os.fspath(root), "daily_prices_path": os.fspath(output), "qa_summary_path": os.fspath(qa_path), "qa": qa}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-path", required=True)
    parser.add_argument("--adj-factor-path", required=True)
    parser.add_argument("--calendar-path", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--ignore-off-calendar-adj", action="store_true", help="Explicitly exclude and count adjustment-only keys on non-calendar dates; never change prices, calendar or IS bounds.")
    args = parser.parse_args()
    print(json.dumps(assemble_market_inputs(daily_path=args.daily_path, adj_factor_path=args.adj_factor_path,
                                             calendar_path=args.calendar_path, output_root=args.output_root, ignore_off_calendar_adj=args.ignore_off_calendar_adj), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
