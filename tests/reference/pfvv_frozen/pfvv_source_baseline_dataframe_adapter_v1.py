"""Local DataFrame adapter for the frozen PF/VV source baseline.

This module deliberately owns no PF/VV mathematics.  It converts already
prepared minute rows into the wide stock-day inputs consumed by
``pfvv_source_baseline_v1`` and delegates all construction to that kernel.
It has no file, network, calendar-discovery, fill, backtest, or writeback
behaviour.

The public entry point follows the Ultimate direct-code shape:
``compute_factor(daily_df=..., minute_df=...)``.  For this adapter ``daily_df``
is *not* a daily-price panel: it is an explicit one-column ``trade_date``
trading-calendar frame.  A caller outside that two-frame interface may instead
pass the same calendar through ``trading_calendar=``.  Supplying an ordinary
daily panel without an explicit calendar is rejected rather than guessed.

This is a local, in-memory, sample-only adapter.  It is not a formal
raw-minute Step4 route, a complete-data assertion, or evidence of a full
IS/OOS evaluation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


_SOURCE_KERNEL_PATH = Path(__file__).with_name("pfvv_source_baseline_v1.py")
_KERNEL_SPEC = importlib.util.spec_from_file_location("pfvv_source_baseline_v1", _SOURCE_KERNEL_PATH)
if _KERNEL_SPEC is None or _KERNEL_SPEC.loader is None:  # pragma: no cover - installation failure
    raise ImportError(f"cannot import frozen PF/VV kernel: {_SOURCE_KERNEL_PATH}")
_KERNEL = importlib.util.module_from_spec(_KERNEL_SPEC)
_KERNEL_SPEC.loader.exec_module(_KERNEL)


IS_START = pd.Timestamp("2016-01-04")
MAX_IS_DATE = pd.Timestamp("2025-07-11")
EXPECTED_SLOTS = 240
REQUIRED_MINUTE_COLUMNS = ("ts_code", "trade_time", "open", "close", "vol")
DEFAULT_MAX_RAW_ROWS = 1_000_000
DEFAULT_MAX_CALENDAR_DAYS = 60
DEFAULT_MAX_ESTIMATED_BYTES = 512 * 1024 * 1024
# The adapter creates several float matrices (prices, volume, returns and
# kernel-internal arrays) before it can reduce a stock-day.  This deliberately
# overestimates the dense ``calendar * 240 * ticker`` shape so sparse inputs
# cannot smuggle a full-panel expansion through a small raw row count.
ESTIMATED_BYTES_PER_EXPANDED_CELL = 96

# This is descriptive metadata for a local source contract.  It does not turn
# this in-memory adapter into a full-window direct-code authorization.
METADATA = {
    "adapter_version": "pfvv_source_baseline_dataframe_adapter_v1",
    "implementation_mode": "direct_code",
    "local_only": True,
    "sample_only": True,
    "formal_full_is_allowed": False,
    "input_contract": {
        "minute_columns": list(REQUIRED_MINUTE_COLUMNS),
        "calendar": "explicit complete trading calendar",
        "minute_clock": "09:31-11:30,13:01-15:00",
        "markets": ["SH", "SZ"],
        "research_window": {"start": "2016-01-04", "end": "2025-07-11"},
        "sample_budget": {
            "max_raw_rows": DEFAULT_MAX_RAW_ROWS,
            "max_calendar_days": DEFAULT_MAX_CALENDAR_DAYS,
            "max_estimated_bytes": DEFAULT_MAX_ESTIMATED_BYTES,
            "estimated_bytes_per_expanded_cell": ESTIMATED_BYTES_PER_EXPANDED_CELL,
        },
    },
    "output_columns": ["ts_code", "trade_date", "factor_value", "PF", "VV", "PF_z", "VV_z"],
    "math_authority": "pfvv_source_baseline_v1",
}


def _as_date_series(values: Any, name: str) -> pd.Series:
    """Parse date keys without accepting an ambiguous/invalid observation."""
    source = pd.Series(values, copy=False)
    if source.empty:
        raise ValueError(f"{name} must not be empty")
    text = source.astype("string").str.strip()
    compact = text.str.fullmatch(r"\d{8}")
    parsed = pd.Series(pd.NaT, index=source.index, dtype="datetime64[ns]")
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    if (~compact).any():
        parsed.loc[~compact] = pd.to_datetime(text.loc[~compact], errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"{name} contains an unparseable date")
    return parsed.dt.normalize()


def _validate_is_dates(dates: pd.Series | pd.DatetimeIndex, name: str) -> None:
    values = pd.DatetimeIndex(dates)
    if (values < IS_START).any() or (values > MAX_IS_DATE).any():
        raise ValueError(f"{name} must remain within 2016-01-04 through 2025-07-11 local IS")


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _assert_local_sample_budget(
    *,
    raw_rows: int,
    calendar_days: int,
    ticker_count: int,
    max_raw_rows: int,
    max_calendar_days: int,
    max_estimated_bytes: int,
) -> None:
    """Block before any per-day pivot/reindex can materialize a dense panel."""
    max_raw_rows = _positive_int(max_raw_rows, "max_raw_rows")
    max_calendar_days = _positive_int(max_calendar_days, "max_calendar_days")
    max_estimated_bytes = _positive_int(max_estimated_bytes, "max_estimated_bytes")
    expanded_cells = calendar_days * EXPECTED_SLOTS * ticker_count
    estimated_bytes = (raw_rows + expanded_cells) * ESTIMATED_BYTES_PER_EXPANDED_CELL
    if (
        raw_rows > max_raw_rows
        or calendar_days > max_calendar_days
        or estimated_bytes > max_estimated_bytes
    ):
        raise ValueError(
            "BLOCK_PFVV_LOCAL_SAMPLE_BUDGET: sample-only adapter refuses a possible full-panel expansion; "
            f"raw_rows={raw_rows} limit={max_raw_rows}; calendar_days={calendar_days} limit={max_calendar_days}; "
            f"calendar_x_240_x_tickers={expanded_cells}; estimated_bytes={estimated_bytes} "
            f"limit={max_estimated_bytes}. Use a bounded local sample, not a full IS panel."
        )


def _calendar_from(value: Any, name: str) -> pd.DatetimeIndex:
    if isinstance(value, pd.DataFrame):
        if set(value.columns) != {"trade_date"}:
            raise ValueError(
                f"{name} must be an explicit one-column trade_date calendar; "
                "do not infer a calendar from an ordinary daily panel"
            )
        dates = _as_date_series(value["trade_date"], name)
    elif isinstance(value, (pd.Series, pd.Index, Sequence)) and not isinstance(value, (str, bytes)):
        dates = _as_date_series(value, name)
    else:
        raise TypeError(f"{name} must be a DataFrame, Series, Index, or date sequence")
    index = pd.DatetimeIndex(dates)
    if index.has_duplicates:
        raise ValueError(f"{name} contains duplicate dates")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{name} must be increasing")
    _validate_is_dates(index, name)
    return index


def _resolve_calendar(daily_df: Any, trading_calendar: Any | None) -> pd.DatetimeIndex:
    if trading_calendar is not None:
        return _calendar_from(trading_calendar, "trading_calendar")
    if daily_df is None:
        raise ValueError("an explicit trading calendar is required (daily_df or trading_calendar)")
    return _calendar_from(daily_df, "daily_df")


def _validate_minute_rows(minute_df: Any, calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.Index]:
    if not isinstance(minute_df, pd.DataFrame):
        raise TypeError("minute_df must be a pandas DataFrame")
    normalized = minute_df.copy()
    # Match the only unambiguous aliases already normalized by the Ultimate
    # direct-code caller, without inventing any data or changing values.
    for canonical, alias in (("trade_time", "datetime"), ("vol", "volume")):
        if canonical not in normalized.columns and alias in normalized.columns:
            normalized[canonical] = normalized[alias]
    missing = set(REQUIRED_MINUTE_COLUMNS) - set(normalized.columns)
    if missing:
        raise KeyError(f"minute_df is missing required columns: {sorted(missing)}")
    if minute_df.empty:
        raise ValueError("minute_df must not be empty")

    frame = normalized.loc[:, list(REQUIRED_MINUTE_COLUMNS)].copy()
    codes = frame["ts_code"].astype("string").str.strip()
    if codes.isna().any() or (codes == "").any():
        raise ValueError("minute_df ts_code contains a missing/empty identity")
    if not codes.str.fullmatch(r"\d{6}\.(?:SH|SZ)").all():
        raise ValueError("minute_df ts_code must be a six-digit SH or SZ code; BJ and unrecognized markets are excluded")
    frame["ts_code"] = codes.astype(str)

    timestamps = pd.to_datetime(frame["trade_time"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("minute_df trade_time contains an unparseable timestamp")
    if getattr(timestamps.dt, "tz", None) is not None:
        raise ValueError("minute_df trade_time must use naive local exchange timestamps")
    frame["_trade_time"] = timestamps
    frame["_trade_date"] = timestamps.dt.normalize()
    _validate_is_dates(frame["_trade_date"], "minute_df trade_time")
    if not frame["_trade_date"].isin(calendar).all():
        raise ValueError("minute_df contains a date absent from the explicit trading calendar")
    # The frozen kernel's canonical clock starts at 09:31.  This rejects both
    # date-only/midnight placeholders and an invented 09:30 opening slot.
    slot_ok = pd.Series(False, index=frame.index)
    for day in pd.DatetimeIndex(frame["_trade_date"].unique()):
        expected = _KERNEL._expected_minute_clock(day)
        day_mask = frame["_trade_date"].eq(day)
        slot_ok.loc[day_mask] = frame.loc[day_mask, "_trade_time"].isin(expected).to_numpy()
    if not slot_ok.all():
        raise ValueError(
            "minute_df trade_time must be real canonical 09:31-11:30/13:01-15:00 minute timestamps; "
            "midnight and 09:30 placeholders are not minutes"
        )
    if frame.duplicated(["ts_code", "_trade_time"]).any():
        raise ValueError("minute_df contains duplicate ts_code/trade_time rows")

    if "trade_date" in normalized.columns:
        declared_dates = _as_date_series(normalized["trade_date"], "minute_df trade_date")
        # Parquet commonly supplies datetime64[us], while explicit date parsing
        # yields datetime64[ns]. Resolution is not a difference in trading day.
        if not declared_dates.index.equals(frame.index) or not declared_dates.eq(frame["_trade_date"]).all():
            raise ValueError("minute_df trade_date disagrees with trade_time")
    codes_index = pd.Index(frame["ts_code"].drop_duplicates(), name="ts_code")
    return frame, codes_index


def _one_day_panels(frame: pd.DataFrame, day: pd.Timestamp, codes: pd.Index) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Build one canonical day without resampling or filling missing observations."""
    expected = _KERNEL._expected_minute_clock(day)
    today = frame.loc[frame["_trade_date"].eq(day)]
    close = today.pivot(index="_trade_time", columns="ts_code", values="close").reindex(index=expected, columns=codes)
    volume = today.pivot(index="_trade_time", columns="ts_code", values="vol").reindex(index=expected, columns=codes)
    opening = today.pivot(index="_trade_time", columns="ts_code", values="open").reindex(index=expected, columns=codes).iloc[0]
    return close, opening, volume


def compute_factor(
    daily_df: pd.DataFrame | None = None,
    minute_df: pd.DataFrame | None = None,
    *,
    trading_calendar: pd.DataFrame | pd.Series | pd.Index | Sequence[object] | None = None,
    max_raw_rows: int = DEFAULT_MAX_RAW_ROWS,
    max_calendar_days: int = DEFAULT_MAX_CALENDAR_DAYS,
    max_estimated_bytes: int = DEFAULT_MAX_ESTIMATED_BYTES,
) -> pd.DataFrame:
    """Return calendar-complete PF/VV factor rows from explicit local frames.

    ``daily_df`` is an explicit one-column ``trade_date`` calendar when the
    standard direct-code call shape is used.  ``trading_calendar`` is provided
    for callers that need to pass a separate calendar and an ordinary daily
    frame; it is never inferred from minute rows.
    """
    calendar = _resolve_calendar(daily_df, trading_calendar)
    frame, codes = _validate_minute_rows(minute_df, calendar)
    _assert_local_sample_budget(
        raw_rows=len(frame),
        calendar_days=len(calendar),
        ticker_count=len(codes),
        max_raw_rows=max_raw_rows,
        max_calendar_days=max_calendar_days,
        max_estimated_bytes=max_estimated_bytes,
    )
    pf_rows: dict[pd.Timestamp, pd.Series] = {}
    vv_rows: dict[pd.Timestamp, pd.Series] = {}
    for day in calendar:
        close, opening, volume = _one_day_panels(frame, day, codes)
        returns = _KERNEL.minute_returns(close, opening)
        pf_rows[day] = _KERNEL.pf_daily(returns, expected_slots=EXPECTED_SLOTS)["daily"]
        vv_rows[day] = _KERNEL.vv_daily(returns, volume, expected_slots=EXPECTED_SLOTS)["daily"]

    components = _KERNEL.rolling_components(
        pd.DataFrame.from_dict(pf_rows, orient="index").reindex(index=calendar, columns=codes),
        pd.DataFrame.from_dict(vv_rows, orient="index").reindex(index=calendar, columns=codes),
        calendar,
        window=20,
    )
    values = pd.concat(
        {
            "factor_value": components["score"],
            "PF": components["pf_raw"],
            "VV": components["vv_raw"],
            "PF_z": components["pf_z"],
            "VV_z": components["vv_z"],
        },
        axis=1,
    )
    values.index.name = "trade_date"
    values.columns.names = [None, "ts_code"]
    out = values.stack(level="ts_code", future_stack=True).reset_index()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y%m%d")
    return out[["ts_code", "trade_date", "factor_value", "PF", "VV", "PF_z", "VV_z"]]


__all__ = ["METADATA", "compute_factor"]
