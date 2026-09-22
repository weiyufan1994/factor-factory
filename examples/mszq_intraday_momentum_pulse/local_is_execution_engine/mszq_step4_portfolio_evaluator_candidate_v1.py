"""Bounded, local-IS MSZQ portfolio evaluator for the Step4 custom-backend hook.

The evaluator consumes only caller-supplied DataFrames (or paths explicitly
named in ``--prepared-inputs``).  It never discovers data, accesses S3/network,
or reads OOS.  It is candidate evidence, not a promotion or capacity claim.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from mszq_evaluation_calendar_candidate_v1 import (
    IS_CUTOFF,
    IS_START,
    CalendarContractError,
    EvaluationWindow,
    build_evaluation_windows,
)
from mszq_v17_normalized_constraints_candidate_v1 import RAW_REQUIRED as V17_RAW_REQUIRED, normalize_v17_constraints


SCHEMA_ID = "mszq_step4_portfolio_evaluator_candidate_v1"
AUTHORITY_EFFECT = "NONE"
EVIDENCE_SCOPE = "LOCAL_IS_ONLY_CANDIDATE_EVALUATION"
BACKEND_NAME = "mszq_portfolio"
ONE_WAY_COST = 0.003
MIN_EFFECTIVE_NAMES = 100
MIN_EFFECTIVE_COVERAGE = 0.70
MIN_DISTINCT_FACTOR_VALUES = 5
MIN_IC_NAMES = 20
LOOKUP_ENGINE = "UNIQUE_STOCK_DAY_MULTIINDEX"
STOCK_DAY_DATE_CACHE_SIZE = 4


class PortfolioEvaluatorError(ValueError):
    """Raised for an incomplete or semantically invalid explicit input."""


def _require_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise PortfolioEvaluatorError(f"{label}_dataframe_required")
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise PortfolioEvaluatorError(f"{label}_missing_columns:{','.join(missing)}")
    if frame.columns.has_duplicates:
        raise PortfolioEvaluatorError(f"{label}_duplicate_column_labels")


def _parse_trade_dates(values: pd.Series) -> pd.Series:
    text = values.astype(str)
    compact = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    ordinary = pd.to_datetime(text, errors="coerce")
    return compact.fillna(ordinary)


def _dates(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    # Keep source value blocks shared until a normalized column is replaced;
    # deep copies of 9m-row prepared tables would create an avoidable peak.
    out = frame.copy(deep=False)
    parsed = _parse_trade_dates(out["trade_date"])
    if parsed.isna().any():
        raise PortfolioEvaluatorError(f"{label}_invalid_trade_date")
    out["trade_date"] = parsed.dt.strftime("%Y-%m-%d")
    return out


def _positive(frame: pd.DataFrame, columns: Iterable[str], label: str) -> pd.DataFrame:
    out = frame.copy(deep=False)
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
        if (~np.isfinite(out[column])) .any() or (out[column] <= 0.0).any():
            raise PortfolioEvaluatorError(f"{label}_invalid_{column}")
    return out


def _closed_bool(value: object, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool) and int(value) in (0, 1):
        return bool(value)
    raise PortfolioEvaluatorError(f"constraints_invalid_boolean:{label}")


def _normalize_inputs(
    factor_values: pd.DataFrame,
    measurement_domain: pd.DataFrame,
    daily_prices: pd.DataFrame,
    execution_vwap: pd.DataFrame,
    normalized_constraints: pd.DataFrame,
    calendar: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    _require_columns(factor_values, {"ts_code", "trade_date", "factor_value"}, "factor")
    _require_columns(measurement_domain, {"ts_code", "trade_date"}, "measurement_domain")
    _require_columns(daily_prices, {"ts_code", "trade_date", "close_unadjusted", "adj_factor"}, "daily")
    _require_columns(execution_vwap, {"ts_code", "trade_date", "vwap_unadjusted", "bar_count", "price_basis"}, "execution")
    _require_columns(
        normalized_constraints,
        {"ts_code", "trade_date", "constraint_complete", "st_new_buy_blocked",
         "pretrade_buy_blocked", "pretrade_sell_blocked", "is_st_asof_trade",
         "up_limit", "down_limit", "historicalstatus_present", "listing_status"},
        "constraints",
    )
    _require_columns(calendar, {"trade_date", "is_open"}, "calendar")
    factor, measurement, daily, execution, constraints, cal = (
        _dates(factor_values, "factor"), _dates(measurement_domain, "measurement_domain"),
        _dates(daily_prices, "daily"), _dates(execution_vwap, "execution"),
        _dates(normalized_constraints, "constraints"), _dates(calendar, "calendar"),
    )
    for label, frame in (("factor", factor), ("measurement_domain", measurement), ("daily", daily), ("execution", execution), ("constraints", constraints)):
        if frame[["ts_code", "trade_date"]].duplicated().any():
            raise PortfolioEvaluatorError(f"{label}_duplicate_stock_day")
        if frame["ts_code"].isna().any() or frame["ts_code"].astype(str).eq("").any():
            raise PortfolioEvaluatorError(f"{label}_invalid_ts_code")
        frame["ts_code"] = frame["ts_code"].astype(str)
        if frame["trade_date"].lt(IS_START.isoformat()).any() or frame["trade_date"].gt(IS_CUTOFF.isoformat()).any():
            raise PortfolioEvaluatorError(f"{label}_outside_frozen_is")
    if cal["trade_date"].duplicated().any():
        raise PortfolioEvaluatorError("calendar_duplicate_trade_date")
    if not cal["is_open"].map(lambda value: _closed_bool(value, "is_open")).all():
        raise PortfolioEvaluatorError("calendar_contains_closed_date")
    calendar_dates = sorted(cal["trade_date"].tolist())
    if not calendar_dates:
        raise PortfolioEvaluatorError("calendar_empty")
    if calendar_dates[0] < IS_START.isoformat() or calendar_dates[-1] > IS_CUTOFF.isoformat():
        raise PortfolioEvaluatorError("calendar_outside_frozen_is")
    daily = _positive(daily, ("close_unadjusted",), "daily")
    daily["adj_factor"] = pd.to_numeric(daily["adj_factor"], errors="coerce")
    invalid_adj = daily["adj_factor"].notna() & (~np.isfinite(daily["adj_factor"]) | (daily["adj_factor"] <= 0.0))
    if invalid_adj.any():
        raise PortfolioEvaluatorError("daily_invalid_adj_factor")
    # A null 16-bar VWAP is a recorded execution-availability gap, not a zero
    # price or an invalid factor observation.  Retain its source-row count,
    # then remove only that row from the execution lookup so existing buy/sell
    # and IC paths consistently see an unavailable price (``None``).  A
    # non-null value that cannot be numeric remains malformed and fails closed.
    raw_vwap = execution["vwap_unadjusted"]
    execution["vwap_unadjusted"] = pd.to_numeric(raw_vwap, errors="coerce")
    malformed_vwap = raw_vwap.notna() & execution["vwap_unadjusted"].isna()
    invalid_vwap = execution["vwap_unadjusted"].notna() & (
        ~np.isfinite(execution["vwap_unadjusted"]) | (execution["vwap_unadjusted"] <= 0.0)
    )
    if malformed_vwap.any() or invalid_vwap.any():
        raise PortfolioEvaluatorError("execution_invalid_vwap_unadjusted")
    missing_vwap_rows = int(execution["vwap_unadjusted"].isna().sum())
    if not execution["bar_count"].map(lambda value: isinstance(value, (int, np.integer, float)) and not isinstance(value, bool) and int(value) == 16).all():
        raise PortfolioEvaluatorError("execution_requires_inclusive_16_bar_vwap")
    if not execution["price_basis"].eq("UNADJUSTED_AMOUNT_OVER_VOL").all():
        raise PortfolioEvaluatorError("execution_requires_unadjusted_amount_over_vol")
    for column in (
        "constraint_complete", "st_new_buy_blocked", "pretrade_buy_blocked",
        "pretrade_sell_blocked", "is_st_asof_trade", "historicalstatus_present",
    ):
        constraints[column] = constraints[column].map(lambda value, name=column: _closed_bool(value, name))
    allowed_listing = {"LISTED", "DELISTING", "DELISTED", "UNKNOWN", "NOT_LISTED"}
    if not constraints["listing_status"].isin(allowed_listing).all():
        raise PortfolioEvaluatorError("constraints_invalid_listing_status")
    if ((constraints["listing_status"] != "UNKNOWN") & ~constraints["historicalstatus_present"]).any():
        raise PortfolioEvaluatorError("constraints_listing_status_without_historical_evidence")
    for column in ("up_limit", "down_limit"):
        constraints[column] = pd.to_numeric(constraints[column], errors="coerce")
    invalid_complete_limits = constraints["constraint_complete"] & (
        ~np.isfinite(constraints["up_limit"]) | ~np.isfinite(constraints["down_limit"])
        | (constraints["up_limit"] <= 0.0) | (constraints["down_limit"] <= 0.0)
        | (constraints["down_limit"] > constraints["up_limit"])
    )
    if invalid_complete_limits.any():
        raise PortfolioEvaluatorError("constraints_complete_limit_reference_invalid")
    if "delist_cash_settlement_unadjusted" not in constraints:
        constraints["delist_cash_settlement_unadjusted"] = np.nan
    constraints["delist_cash_settlement_unadjusted"] = pd.to_numeric(
        constraints["delist_cash_settlement_unadjusted"], errors="coerce"
    )
    bad_settlement = constraints["delist_cash_settlement_unadjusted"].notna() & (
        ~np.isfinite(constraints["delist_cash_settlement_unadjusted"]) | (constraints["delist_cash_settlement_unadjusted"] <= 0)
    )
    if bad_settlement.any():
        raise PortfolioEvaluatorError("constraints_invalid_delist_settlement")
    factor["factor_value"] = pd.to_numeric(factor["factor_value"], errors="coerce")
    execution = execution.loc[execution["vwap_unadjusted"].notna()].copy(deep=False)
    execution.attrs["missing_vwap_rows"] = missing_vwap_rows
    return factor, measurement, daily, execution, constraints, calendar_dates


def _stock_day_lookup_pandas(frame: pd.DataFrame) -> pd.DataFrame:
    """Reference lookup oracle: one unique-key MultiIndex."""
    return frame.set_index(["ts_code", "trade_date"], drop=True, verify_integrity=True)


def _row_pandas(lookup: pd.DataFrame, code: str, trade_date: str) -> pd.Series | None:
    try:
        return lookup.loc[(code, trade_date)]
    except KeyError:
        return None


class _CachedStockDayRow:
    """Read-only scalar view of one unique stock-day row.

    The evaluator only consumes named scalars.  Avoiding a pandas Series per
    repeated lookup is therefore observationally equivalent while preserving
    NaN and native scalar values from the indexed source columns.
    """
    __slots__ = ("_columns", "_position")

    def __init__(self, columns: dict[str, np.ndarray], position: int) -> None:
        self._columns = columns
        self._position = position

    def __getitem__(self, column: str) -> object:
        return self._columns[column][self._position]


class _BoundedStockDayRows:
    """Bounded LRU cache of up to four date partitions from a MultiIndex."""
    def __init__(self, indexed: pd.DataFrame, *, max_dates: int = STOCK_DAY_DATE_CACHE_SIZE) -> None:
        self._indexed = indexed
        self._max_dates = max_dates
        # Construct grouping positions once.  ``xs(level='trade_date')`` on an
        # unsorted secondary MultiIndex level can scan the entire input for
        # every date; ``take`` below only materializes the named date rows.
        self._date_positions = {
            str(trade_date): np.asarray(positions, dtype=np.intp)
            for trade_date, positions in indexed.groupby(level="trade_date", sort=False).indices.items()
        }
        self._dates: OrderedDict[str, tuple[dict[str, int], dict[str, np.ndarray], dict[str, _CachedStockDayRow]] | None] = OrderedDict()
        self._partition_build_counts: dict[str, int] = {}

    def _date_partition(self, trade_date: str) -> tuple[dict[str, int], dict[str, np.ndarray], dict[str, _CachedStockDayRow]] | None:
        if trade_date in self._dates:
            cached = self._dates.pop(trade_date)
            self._dates[trade_date] = cached
            return cached
        source_positions = self._date_positions.get(trade_date)
        self._partition_build_counts[trade_date] = self._partition_build_counts.get(trade_date, 0) + 1
        if source_positions is None:
            cached = None
        else:
            rows = self._indexed.take(source_positions)
            positions = {
                str(code): ordinal
                for ordinal, code in enumerate(rows.index.get_level_values("ts_code").tolist())
            }
            columns = {str(column): rows[column].to_numpy(copy=False) for column in rows.columns}
            cached = (positions, columns, {})
        self._dates[trade_date] = cached
        if len(self._dates) > self._max_dates:
            self._dates.popitem(last=False)
        return cached

    def row(self, code: str, trade_date: str) -> _CachedStockDayRow | None:
        partition = self._date_partition(trade_date)
        if partition is None:
            return None
        positions, columns, rows = partition
        key = str(code)
        position = positions.get(key)
        if position is None:
            return None
        cached = rows.get(key)
        if cached is None:
            cached = _CachedStockDayRow(columns, position)
            rows[key] = cached
        return cached


def _stock_day_lookup(frame: pd.DataFrame) -> _BoundedStockDayRows:
    """Build the reference MultiIndex plus a bounded date-local row cache."""
    return _BoundedStockDayRows(_stock_day_lookup_pandas(frame))


def _row(lookup: pd.DataFrame | _BoundedStockDayRows, code: str, trade_date: str) -> pd.Series | _CachedStockDayRow | None:
    if isinstance(lookup, _BoundedStockDayRows):
        return lookup.row(code, trade_date)
    return _row_pandas(lookup, code, trade_date)


def _date_lookup(frame: pd.DataFrame) -> pd.DataFrame:
    """Index daily controller objects once, avoiding a full factor scan per month."""
    return frame.set_index("trade_date", drop=True)


def _date_rows(lookup: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    try:
        rows = lookup.loc[trade_date]
    except KeyError:
        return lookup.iloc[0:0].copy()
    return rows.to_frame().T if isinstance(rows, pd.Series) else rows


def _validate_factor_domain(factor_by_date: pd.DataFrame, measurement_by_date: pd.DataFrame) -> None:
    """Validate keys date-by-date to avoid a full 9m-row merge temporary."""
    for trade_date in factor_by_date.index.unique():
        factor_codes = _date_rows(factor_by_date, str(trade_date))["ts_code"]
        measurement_codes = _date_rows(measurement_by_date, str(trade_date))["ts_code"]
        if not factor_codes.isin(measurement_codes).all():
            raise PortfolioEvaluatorError("factor_outside_explicit_measurement_domain")


def _adj_available(row: pd.Series | None) -> bool:
    return row is not None and bool(np.isfinite(float(row["adj_factor"]))) and float(row["adj_factor"]) > 0.0


def _selection(factor_by_date: pd.DataFrame, measurement_by_date: pd.DataFrame, window: EvaluationWindow) -> tuple[pd.DataFrame, dict[str, object]]:
    formation = window.formation_date.isoformat()
    domain = _date_rows(measurement_by_date, formation)[["ts_code"]].copy()
    observed = _date_rows(factor_by_date, formation)[["ts_code", "factor_value"]].copy()
    # The controller's domain stays left; absence of a factor row is a receive
    # gap, while an explicit NaN is an invalid measurement.  Neither becomes 0.
    day = domain.merge(observed, on=["ts_code"], how="left", indicator=True, validate="one_to_one")
    supplied = len(domain)
    received = int(day["_merge"].eq("both").sum())
    valid = day.loc[np.isfinite(day["factor_value"])].copy()
    n_valid = len(valid)
    coverage = n_valid / supplied if supplied else 0.0
    distinct = int(valid["factor_value"].nunique())
    status = "READY"
    if supplied == 0:
        status = "NO_MEASUREMENT_DOMAIN"
    elif n_valid < MIN_EFFECTIVE_NAMES:
        status = "COLLAPSED_INSUFFICIENT_EFFECTIVE_NAMES"
    elif coverage < MIN_EFFECTIVE_COVERAGE:
        status = "COLLAPSED_INSUFFICIENT_EFFECTIVE_COVERAGE"
    elif distinct < MIN_DISTINCT_FACTOR_VALUES:
        status = "COLLAPSED_INSUFFICIENT_DISTINCT_VALUES"
    if status != "READY":
        return valid.iloc[0:0], {
            "formation_date": window.formation_date.isoformat(), "selection_status": status,
            # This is the complete controller-derived measurement domain, prior
            # to any PF, price, or execution filtering; NaN observations stay in
            # its denominator instead of becoming manufactured zero events.
            "expected_measurement_rows": supplied, "received_measurement_rows": received,
            "finite_factor_rows": n_valid, "missing_or_invalid_factor_rows": supplied - n_valid,
            "effective_coverage": coverage, "distinct_factor_values": distinct, "selected_count": 0,
        }
    ordered = valid.sort_values(["factor_value", "ts_code"], ascending=[False, True], kind="mergesort")
    target = int(math.ceil(n_valid * 0.20))
    boundary = float(ordered.iloc[target - 1]["factor_value"])
    # Inclusion at the boundary is value-based; ticker order is never a tie breaker.
    selected = ordered.loc[ordered["factor_value"] >= boundary].copy()
    return selected, {
        "formation_date": window.formation_date.isoformat(), "selection_status": "READY",
        "expected_measurement_rows": supplied, "received_measurement_rows": received,
        "finite_factor_rows": n_valid, "missing_or_invalid_factor_rows": supplied - n_valid,
        "effective_coverage": coverage, "distinct_factor_values": distinct,
        "selected_count": len(selected), "quintile_boundary": boundary,
    }


def _formation_dates_from_calendar(
    calendar_dates: list[str], factor_dates: Iterable[str], complete_months: Iterable[str],
) -> list[str]:
    """Use calendar month-ends only; daily derived-state rows are not signals."""
    last_open_by_month: dict[str, str] = {}
    for trade_date in calendar_dates:
        last_open_by_month[trade_date[:7]] = trade_date
    factor_date_set = set(factor_dates)
    return [
        month_end for month, month_end in last_open_by_month.items()
        if month in set(complete_months) and month_end in factor_date_set
    ]


def _buy_reason(constraint: pd.Series | None, execution: pd.Series | None) -> str | None:
    if constraint is None:
        return "BUY_BLOCKED_CONSTRAINT_MISSING"
    if not bool(constraint["constraint_complete"]):
        return "BUY_BLOCKED_CONSTRAINT_UNKNOWN"
    if bool(constraint["st_new_buy_blocked"]) or bool(constraint["is_st_asof_trade"]):
        return "BUY_BLOCKED_ST"
    # UNKNOWN is an evidence gap, not an invented delisting event.  V17 can
    # still support the ordinary order decision; payloads keep the gap visible.
    if str(constraint["listing_status"]) in {"DELISTED", "DELISTING", "NOT_LISTED"}:
        return "BUY_BLOCKED_LISTING_STATUS"
    if bool(constraint["pretrade_buy_blocked"]):
        return "BUY_BLOCKED_PRETRADE"
    if execution is None:
        return "BUY_BLOCKED_EXECUTION_PRICE_MISSING"
    if not np.isfinite(constraint["up_limit"]) or not np.isfinite(constraint["down_limit"]):
        return "BUY_BLOCKED_LIMIT_REFERENCE_MISSING"
    price = float(execution["vwap_unadjusted"])
    if price < float(constraint["down_limit"]):
        return "BUY_BLOCKED_VWAP_BELOW_DOWN_LIMIT_SOURCE_CONTRADICTION"
    if price >= float(constraint["up_limit"]):
        return "BUY_BLOCKED_AT_OR_ABOVE_UP_LIMIT"
    return None


def _sell_reason(constraint: pd.Series | None, execution: pd.Series | None) -> str | None:
    if constraint is None:
        return "SELL_BLOCKED_CONSTRAINT_MISSING"
    if not bool(constraint["constraint_complete"]):
        return "SELL_BLOCKED_CONSTRAINT_UNKNOWN"
    if bool(constraint["pretrade_sell_blocked"]):
        return "SELL_BLOCKED_PRETRADE"
    if execution is None:
        return "SELL_BLOCKED_EXECUTION_PRICE_MISSING"
    if not np.isfinite(constraint["up_limit"]) or not np.isfinite(constraint["down_limit"]):
        return "SELL_BLOCKED_LIMIT_REFERENCE_MISSING"
    price = float(execution["vwap_unadjusted"])
    if price > float(constraint["up_limit"]):
        return "SELL_BLOCKED_VWAP_ABOVE_UP_LIMIT_SOURCE_CONTRADICTION"
    if price <= float(constraint["down_limit"]):
        return "SELL_BLOCKED_AT_OR_BELOW_DOWN_LIMIT"
    return None


def _monthly_ic(
    factor_by_date: pd.DataFrame, daily_lookup: pd.DataFrame, execution_lookup: pd.DataFrame, windows: Iterable[EvaluationWindow]
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for window in windows:
        row: dict[str, object] = {"formation_date": window.formation_date.isoformat(), "entry_date": None if window.entry_date is None else window.entry_date.isoformat(), "exit_date": None if window.exit_date is None else window.exit_date.isoformat(), "label_status": window.status, "label_count": 0, "pearson_ic": np.nan, "rank_ic": np.nan}
        if window.status != "MATURE":
            rows.append(row)
            continue
        signal = _date_rows(factor_by_date, window.formation_date.isoformat())
        signal = signal.loc[np.isfinite(signal["factor_value"]), ["ts_code", "factor_value"]]
        values: list[tuple[float, float]] = []
        for item in signal.itertuples(index=False):
            entry_exec, exit_exec = _row(execution_lookup, item.ts_code, window.entry_date.isoformat()), _row(execution_lookup, item.ts_code, window.exit_date.isoformat())
            entry_daily, exit_daily = _row(daily_lookup, item.ts_code, window.entry_date.isoformat()), _row(daily_lookup, item.ts_code, window.exit_date.isoformat())
            if entry_exec is None or exit_exec is None or not _adj_available(entry_daily) or not _adj_available(exit_daily):
                continue
            label = (float(exit_exec["vwap_unadjusted"]) * float(exit_daily["adj_factor"])) / (float(entry_exec["vwap_unadjusted"]) * float(entry_daily["adj_factor"])) - 1.0
            values.append((float(item.factor_value), label))
        row["label_count"] = len(values)
        if len(values) >= MIN_IC_NAMES:
            sample = pd.DataFrame(values, columns=["factor", "label"])
            if sample["factor"].nunique() < 2 or sample["label"].nunique() < 2:
                row["label_status"] = "IC_CONSTANT_INPUT"
            else:
                row["pearson_ic"] = sample["factor"].corr(sample["label"], method="pearson")
                row["rank_ic"] = sample["factor"].corr(sample["label"], method="spearman")
                row["label_status"] = "IC_READY"
        else:
            row["label_status"] = "INSUFFICIENT_IC_NAMES"
        rows.append(row)
    return pd.DataFrame(rows)


def _simulate_day_events(
    windows: Iterable[EvaluationWindow], selections: dict[str, pd.DataFrame], daily_lookup: pd.DataFrame,
    execution_lookup: pd.DataFrame, constraint_lookup: pd.DataFrame, calendar_dates: list[str], initial_cash: float = 1.0,
    cost_rate: float = ONE_WAY_COST,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    entries: dict[str, list[EvaluationWindow]] = {}
    for window in windows:
        if window.status == "MATURE" and window.entry_date is not None:
            entries.setdefault(window.entry_date.isoformat(), []).append(window)
    if not np.isfinite(cost_rate) or cost_rate < 0.0:
        raise PortfolioEvaluatorError("cost_rate_must_be_finite_nonnegative")
    cash, prior_nav = float(initial_cash), float(initial_cash)
    positions: list[dict[str, object]] = []
    for trade_date in calendar_dates:
        trades: list[dict[str, object]] = []
        # Exit attempts precede all same-day entries; blocked sells remain live.
        still_open: list[dict[str, object]] = []
        for position in positions:
            code = str(position["ts_code"])
            due = str(position["scheduled_exit_date"]) <= trade_date
            constraint, daily_row = _row(constraint_lookup, code, trade_date), _row(daily_lookup, code, trade_date)
            if position.get("unvalued_delisted", False):
                still_open.append(position)
                continue
            # A separately confirmed delisting resolves immediately on its
            # evidence date.  We never keep marking a known delisted position
            # with later ordinary quotes while waiting for its scheduled exit.
            if constraint is not None and str(constraint["listing_status"]) == "DELISTED":
                settlement = constraint["delist_cash_settlement_unadjusted"]
                if pd.notna(settlement) and _adj_available(daily_row):
                    proceeds = float(position["units"]) * float(settlement) * float(daily_row["adj_factor"])
                    cash += proceeds
                    trades.append({"trade_date": trade_date, "formation_date": position["formation_date"], "ts_code": code, "side": "DELIST_SETTLEMENT", "status": "FILLED", "reason": "DELIST_CASH_SETTLEMENT", "raw_execution_price": float(settlement), "adj_factor": float(daily_row["adj_factor"]), "gross_amount": proceeds, "cost": 0.0, "net_cash_flow": proceeds})
                    continue
                position["unvalued_delisted"] = True
                trades.append({"trade_date": trade_date, "formation_date": position["formation_date"], "ts_code": code, "side": "SELL", "status": "BLOCKED", "reason": "SELL_UNVALUED_DELISTED_NO_SETTLEMENT", "raw_execution_price": np.nan, "adj_factor": np.nan, "gross_amount": np.nan, "cost": np.nan, "net_cash_flow": np.nan})
                still_open.append(position)
                continue
            if not due:
                still_open.append(position)
                continue
            exec_row = _row(execution_lookup, code, trade_date)
            reason = _sell_reason(constraint, exec_row)
            if reason is not None or not _adj_available(daily_row):
                reason = reason or "SELL_BLOCKED_ADJ_FACTOR_MISSING"
                trades.append({"trade_date": trade_date, "formation_date": position["formation_date"], "ts_code": code, "side": "SELL", "status": "BLOCKED", "reason": reason, "raw_execution_price": np.nan if exec_row is None else float(exec_row["vwap_unadjusted"]), "adj_factor": np.nan if daily_row is None else float(daily_row["adj_factor"]), "gross_amount": np.nan, "cost": np.nan, "net_cash_flow": np.nan})
                still_open.append(position)
                continue
            gross = float(position["units"]) * float(exec_row["vwap_unadjusted"]) * float(daily_row["adj_factor"])
            cost = gross * cost_rate
            cash += gross - cost
            trades.append({"trade_date": trade_date, "formation_date": position["formation_date"], "ts_code": code, "side": "SELL", "status": "FILLED", "reason": "SCHEDULED_EXIT", "raw_execution_price": float(exec_row["vwap_unadjusted"]), "adj_factor": float(daily_row["adj_factor"]), "gross_amount": gross, "cost": cost, "net_cash_flow": gross - cost})
        positions = still_open
        for window in entries.get(trade_date, []):
            selected = selections[window.formation_date.isoformat()]
            budget = cash / (len(selected) * (1.0 + cost_rate)) if len(selected) else 0.0
            for item in selected.itertuples(index=False):
                code = str(item.ts_code)
                constraint, exec_row, daily_row = _row(constraint_lookup, code, trade_date), _row(execution_lookup, code, trade_date), _row(daily_lookup, code, trade_date)
                reason = _buy_reason(constraint, exec_row)
                if reason is None and not _adj_available(daily_row):
                    reason = "BUY_BLOCKED_ADJ_FACTOR_MISSING"
                if reason is None and budget <= 0.0:
                    reason = "BUY_BLOCKED_NO_CASH"
                if reason is not None:
                    trades.append({"trade_date": trade_date, "formation_date": window.formation_date.isoformat(), "ts_code": code, "side": "BUY", "status": "BLOCKED", "reason": reason, "raw_execution_price": np.nan if exec_row is None else float(exec_row["vwap_unadjusted"]), "adj_factor": np.nan if daily_row is None else float(daily_row["adj_factor"]), "gross_amount": 0.0, "cost": 0.0, "net_cash_flow": 0.0})
                    continue
                price, adj = float(exec_row["vwap_unadjusted"]), float(daily_row["adj_factor"])
                cost = budget * cost_rate
                cash -= budget + cost
                positions.append({"ts_code": code, "formation_date": window.formation_date.isoformat(), "scheduled_exit_date": window.exit_date.isoformat(), "units": budget / (price * adj), "last_value": budget, "stale_days": 0, "longest_stale_days": 0, "unvalued_delisted": False})
                trades.append({"trade_date": trade_date, "formation_date": window.formation_date.isoformat(), "ts_code": code, "side": "BUY", "status": "FILLED", "reason": "MONTH_END_TOP_QUINTILE", "raw_execution_price": price, "adj_factor": adj, "gross_amount": budget, "cost": cost, "net_cash_flow": -(budget + cost)})
        market_value, stale_mark_value, stale_positions, unknown_positions, unknown_listing_positions = 0.0, 0.0, 0, 0, 0
        for position in positions:
            code = str(position["ts_code"])
            constraint, mark = _row(constraint_lookup, code, trade_date), _row(daily_lookup, code, trade_date)
            if constraint is None or str(constraint["listing_status"]) in {"UNKNOWN", "NOT_LISTED"}:
                unknown_listing_positions += 1
            if position.get("unvalued_delisted", False) or (constraint is not None and str(constraint["listing_status"]) == "DELISTED" and pd.isna(constraint["delist_cash_settlement_unadjusted"])):
                position["unvalued_delisted"] = True
                unknown_positions += 1
                continue
            if not _adj_available(mark):
                position["stale_days"] = int(position["stale_days"]) + 1
                position["longest_stale_days"] = max(int(position["longest_stale_days"]), int(position["stale_days"]))
                stale_positions += 1
                stale_value = float(position["last_value"])
                stale_mark_value += stale_value
                market_value += stale_value
            else:
                position["stale_days"] = 0
                value = float(position["units"]) * float(mark["close_unadjusted"]) * float(mark["adj_factor"])
                position["last_value"] = value
                market_value += value
        nav = np.nan if unknown_positions else cash + market_value
        status = "UNKNOWN_DELISTED_VALUE" if unknown_positions else "STALE_MARK" if stale_positions else "COMPLETE"
        daily_return = nav / prior_nav - 1.0 if np.isfinite(nav) and np.isfinite(prior_nav) else np.nan
        stale_fraction = stale_mark_value / nav if not unknown_positions and np.isfinite(nav) and nav > 0.0 else np.nan
        nav_row = {"trade_date": trade_date, "nav": nav, "daily_return": daily_return, "cash": cash, "market_value": market_value if not unknown_positions else np.nan, "open_position_count": len(positions), "stale_mark_position_count": stale_positions, "stale_mark_value": stale_mark_value if not unknown_positions else np.nan, "stale_mark_nav_fraction": stale_fraction, "longest_stale_days": max((int(position["longest_stale_days"]) for position in positions), default=0), "current_stale_consecutive_days": max((int(position["stale_days"]) for position in positions), default=0), "unvalued_delisted_position_count": unknown_positions, "unknown_listing_status_position_count": unknown_listing_positions, "nav_status": status}
        prior_nav = nav
        yield nav_row, trades

TRADE_COLUMNS = [
    "trade_date", "formation_date", "ts_code", "side", "status", "reason",
    "raw_execution_price", "adj_factor", "gross_amount", "cost", "net_cash_flow",
]


def _simulate(windows, selections, daily_lookup, execution_lookup, constraint_lookup,
              calendar_dates, initial_cash=1.0, cost_rate=ONE_WAY_COST):
    """Compatibility collector over the single economic transition generator."""
    nav_rows, trades = [], []
    for nav, events in _simulate_day_events(windows, selections, daily_lookup, execution_lookup,
            constraint_lookup, calendar_dates, initial_cash=initial_cash, cost_rate=cost_rate):
        nav_rows.append(nav); trades.extend(events)
    return pd.DataFrame(nav_rows), pd.DataFrame(trades, columns=TRADE_COLUMNS)


def _simulate_many(windows, requests, daily_lookup, execution_lookup, constraint_lookup, calendar_dates):
    """Advance independent accounts by date, sharing only read-only lookups.

    Day events are spooled privately so 22 complete ledgers never coexist in
    memory. Each result is rehydrated once, in request order, then released by
    the caller. There is exactly one economic transition implementation.
    """
    import pickle
    import tempfile
    from contextlib import ExitStack
    windows = tuple(windows)
    with tempfile.TemporaryDirectory(prefix='pfvv-account-events-') as root, ExitStack() as stack:
        generators, streams = [], []
        for index, request in enumerate(requests):
            generators.append(_simulate_day_events(windows, request['selections'], daily_lookup,
                execution_lookup, constraint_lookup, calendar_dates, cost_rate=request['cost_rate']))
            streams.append(stack.enter_context(open(Path(root)/f'{index}.events', 'w+b')))
        for day in calendar_dates:
            for iterator, stream in zip(generators, streams):
                nav, trades = next(iterator)
                if nav['trade_date'] != day:
                    raise PortfolioEvaluatorError('account_calendar_synchronization_mismatch')
                pickle.dump((nav, trades), stream, protocol=pickle.HIGHEST_PROTOCOL)
        for iterator in generators:
            if next(iterator, None) is not None:
                raise PortfolioEvaluatorError('account_calendar_extra_day')
        for request, stream in zip(requests, streams):
            stream.seek(0)
            nav_rows, trades = [], []
            while True:
                try:
                    nav, events = pickle.load(stream)
                except EOFError:
                    break
                nav_rows.append(nav); trades.extend(events)
            yield request['key'], pd.DataFrame(nav_rows), pd.DataFrame(trades, columns=TRADE_COLUMNS)


def _nav_metrics(nav: pd.DataFrame, trades: pd.DataFrame) -> dict[str, object]:
    """Compute complete-series performance only; unknown valuation stays NaN."""
    result: dict[str, object] = {"day_count": int(len(nav))}
    for prefix, nav_column, return_column in (("net", "nav", "daily_return"), ("gross", "gross_nav", "gross_daily_return")):
        values = pd.to_numeric(nav[nav_column], errors="coerce")
        returns = pd.to_numeric(nav[return_column], errors="coerce")
        complete = values.notna().all() and returns.notna().all() and (values > 0).all()
        result[f"{prefix}_valuation_complete"] = bool(complete)
        # Compounding the explicit daily series also works for a later calendar
        # year in the continuing global account (whose first NAV is not 1.0).
        result[f"{prefix}_geometric_return"] = float((1.0 + returns).prod() - 1.0) if complete else np.nan
        result[f"{prefix}_annualized_return"] = float((1.0 + returns).prod() ** (252.0 / len(returns)) - 1.0) if complete and len(returns) else np.nan
        if complete and len(returns) > 1:
            std = float(returns.std(ddof=1))
            result[f"{prefix}_daily_volatility"] = std
            result[f"{prefix}_annualized_volatility"] = float(std * np.sqrt(252.0))
            result[f"{prefix}_annualized_daily_sharpe"] = np.nan if std == 0.0 else float(np.sqrt(252.0) * returns.mean() / std)
            peak = values.cummax()
            drawdown = values / peak - 1.0
            trough_index = int(drawdown.to_numpy().argmin())
            result[f"{prefix}_max_drawdown"] = float(drawdown.iloc[trough_index])
            result[f"{prefix}_drawdown_area"] = float((-drawdown).sum())
            peak_before = float(peak.iloc[trough_index])
            recovered = np.flatnonzero(values.iloc[trough_index + 1 :].to_numpy() >= peak_before)
            result[f"{prefix}_recovery_status"] = "NOT_RECOVERED_BY_WINDOW_END" if len(recovered) == 0 else "RECOVERED"
            result[f"{prefix}_recovery_days"] = (
                np.nan if len(recovered) == 0 else int(recovered[0] + 1)
            )
            result[f"{prefix}_recovery_lower_bound_days"] = (
                int(len(values) - 1 - trough_index) if len(recovered) == 0 else np.nan
            )
            result[f"{prefix}_recovery_observation_end"] = str(nav["trade_date"].iloc[-1])
        else:
            result.update({
                f"{prefix}_daily_volatility": np.nan,
                f"{prefix}_annualized_volatility": np.nan,
                f"{prefix}_annualized_daily_sharpe": np.nan,
                f"{prefix}_max_drawdown": np.nan,
                f"{prefix}_drawdown_area": np.nan,
                f"{prefix}_recovery_status": "METRIC_UNAVAILABLE",
                f"{prefix}_recovery_days": np.nan,
                f"{prefix}_recovery_lower_bound_days": np.nan,
                f"{prefix}_recovery_observation_end": None,
            })
    filled = trades.loc[trades["status"].eq("FILLED")]
    result["turnover_gross_amount"] = float(filled["gross_amount"].sum()) if not filled.empty else 0.0
    result["cost_sum"] = float(filled["cost"].sum()) if not filled.empty else 0.0
    return result


def _attach_zero_cost_counterfactual(net_nav: pd.DataFrame, zero_cost_nav: pd.DataFrame) -> pd.DataFrame:
    """Attach a separately simulated zero-cost account, never a cost addback."""
    if not net_nav["trade_date"].equals(zero_cost_nav["trade_date"]):
        raise PortfolioEvaluatorError("zero_cost_counterfactual_calendar_mismatch")
    out = net_nav.copy()
    out["gross_nav"] = zero_cost_nav["nav"].to_numpy()
    out["gross_daily_return"] = zero_cost_nav["daily_return"].to_numpy()
    return out


def _stale_metadata(nav: pd.DataFrame) -> dict[str, object]:
    fractions = pd.to_numeric(nav["stale_mark_nav_fraction"], errors="coerce")
    valid = fractions[np.isfinite(fractions)]
    stale_days = nav["stale_mark_position_count"].gt(0).to_numpy(dtype=bool)
    longest_run, current_run = 0, 0
    for has_stale in stale_days:
        current_run = current_run + 1 if has_stale else 0
        longest_run = max(longest_run, current_run)
    end = fractions.iloc[-1]
    return {
        "max_stale_fraction": None if valid.empty else float(valid.max()),
        "end_stale_fraction": None if not np.isfinite(end) else float(end),
        "max_consecutive_stale_days": int(longest_run),
        "max_position_stale_days": int(nav["longest_stale_days"].max()),
    }


def _matched_eligible_ew_benchmark(
    windows: Iterable[EvaluationWindow], factor_by_date: pd.DataFrame, daily_lookup: pd.DataFrame,
    execution_lookup: pd.DataFrame, constraint_lookup: pd.DataFrame, calendar_dates: list[str],
) -> pd.DataFrame:
    """Diagnostic equal-weight benchmark from the same formation measurement domain.

    It is not an index, has no capital/capacity claim, and uses no future
    execution-constraint filtering.  Entry eligibility is evaluated only at the
    scheduled entry VWAP; daily values are raw-price times adj-factor marks.
    """
    cohorts: list[dict[str, object]] = []
    for window in windows:
        if window.status != "MATURE" or window.entry_date is None or window.exit_date is None:
            continue
        signal = _date_rows(factor_by_date, window.formation_date.isoformat())
        signal = signal.loc[np.isfinite(signal["factor_value"])]
        eligible: list[tuple[str, float]] = []
        for item in signal.itertuples(index=False):
            code = str(item.ts_code)
            reason = _buy_reason(_row(constraint_lookup, code, window.entry_date.isoformat()), _row(execution_lookup, code, window.entry_date.isoformat()))
            entry_daily = _row(daily_lookup, code, window.entry_date.isoformat())
            if reason is None and _adj_available(entry_daily):
                exec_row = _row(execution_lookup, code, window.entry_date.isoformat())
                eligible.append((code, float(exec_row["vwap_unadjusted"]) * float(entry_daily["adj_factor"])))
        if eligible:
            cohorts.append({"entry": window.entry_date.isoformat(), "exit": window.exit_date.isoformat(), "values": eligible})
    rows: list[dict[str, object]] = []
    prior = 1.0
    for day in calendar_dates:
        active_values: list[float] = []
        incomplete = 0
        active_names = 0
        for cohort in cohorts:
            if not cohort["entry"] <= day <= cohort["exit"]:
                continue
            values: list[float] = []
            for code, entry_value in cohort["values"]:
                mark = _row(daily_lookup, code, day)
                if not _adj_available(mark):
                    incomplete += 1
                    continue
                active_names += 1
                values.append(float(mark["close_unadjusted"]) * float(mark["adj_factor"]) / entry_value)
            if values:
                active_values.append(float(np.mean(values)))
        nav = float(np.mean(active_values)) if active_values else np.nan
        status = "MATCHED_ELIGIBLE_EW_INCOMPLETE_MARK" if incomplete else "MATCHED_ELIGIBLE_EW_DIAGNOSTIC"
        daily_return = nav / prior - 1.0 if np.isfinite(nav) and np.isfinite(prior) else np.nan
        rows.append({"trade_date": day, "benchmark_nav": nav, "benchmark_daily_return": daily_return, "benchmark_status": status, "active_cohort_count": len(active_values), "active_name_count": active_names, "missing_mark_count": incomplete})
        prior = nav
    return pd.DataFrame(rows)


def evaluate_from_frames(*, factor_values: pd.DataFrame, measurement_domain: pd.DataFrame, daily_prices: pd.DataFrame, execution_vwap: pd.DataFrame, normalized_constraints: pd.DataFrame, calendar: pd.DataFrame, complete_months: Iterable[str]) -> dict[str, pd.DataFrame]:
    """Evaluate a supplied IS slice without I/O or any implicit data lookup."""
    factors, measurement, daily, execution, constraints, dates = _normalize_inputs(factor_values, measurement_domain, daily_prices, execution_vwap, normalized_constraints, calendar)
    # _normalize_inputs returns shallow-normalized frames.  The un-normalized
    # function arguments otherwise stay alive through the costly MultiIndex
    # construction below, despite no longer carrying any distinct information.
    # Releasing only those redundant references preserves the evaluator's
    # selection, execution, valuation, and output semantics.
    del factor_values, measurement_domain, daily_prices, execution_vwap, normalized_constraints, calendar
    input_row_counts = {"factor_rows": len(factors), "daily_rows": len(daily), "execution_rows": len(execution) + int(execution.attrs.get("missing_vwap_rows", 0)), "execution_usable_rows": len(execution), "constraint_rows": len(constraints), "measurement_domain_rows": len(measurement)}
    daily_adj_factor_missing_rows = int(daily["adj_factor"].isna().sum())
    execution_missing_vwap_rows = int(execution.attrs.get("missing_vwap_rows", 0))
    factor_dates = factors["trade_date"].unique().tolist()
    factor_by_date, measurement_by_date = _date_lookup(factors), _date_lookup(measurement)
    _validate_factor_domain(factor_by_date, measurement_by_date)
    daily_lookup, execution_lookup, constraint_lookup = _stock_day_lookup(daily), _stock_day_lookup(execution), _stock_day_lookup(constraints)
    # The indexed tables retain the values needed downstream.  Releasing the
    # pre-index frame references avoids a second live table copy at IS scale.
    del factors, measurement, daily, execution, constraints
    complete_months = tuple(complete_months)
    signal_dates = _formation_dates_from_calendar(
        dates, factor_dates, complete_months
    )
    try:
        windows = build_evaluation_windows(dates, signal_dates, complete_months=complete_months, cutoff=dates[-1])
    except CalendarContractError as exc:
        raise PortfolioEvaluatorError(f"calendar_contract:{exc}") from exc
    selections, coverage_rows = {}, []
    for window in windows:
        selected, coverage = _selection(factor_by_date, measurement_by_date, window)
        selections[window.formation_date.isoformat()] = selected
        coverage_rows.append(coverage)
    nav, trades = _simulate(windows, selections, daily_lookup, execution_lookup, constraint_lookup, dates, cost_rate=ONE_WAY_COST)
    zero_cost_nav, _ = _simulate(windows, selections, daily_lookup, execution_lookup, constraint_lookup, dates, cost_rate=0.0)
    nav = _attach_zero_cost_counterfactual(nav, zero_cost_nav)
    ic = _monthly_ic(factor_by_date, daily_lookup, execution_lookup, windows)
    benchmark = _matched_eligible_ew_benchmark(windows, factor_by_date, daily_lookup, execution_lookup, constraint_lookup, dates)
    performance = _nav_metrics(nav, trades)
    annual_rows: list[dict[str, object]] = []
    nav["calendar_year"] = nav["trade_date"].str[:4]
    for year, group in nav.groupby("calendar_year", sort=True):
        annual = _nav_metrics(group, trades.loc[trades["trade_date"].str.startswith(str(year))])
        annual_rows.append({"year": year, "scope": "GLOBAL_ACCOUNT_DAILY_RETURNS", **annual})
        annual_windows = [window for window in windows if window.status == "MATURE" and window.formation_date.year == int(year) and window.entry_date.year == int(year) and window.exit_date.year == int(year)]
        if annual_windows:
            year_dates = [value for value in dates if value.startswith(f"{year}-")]
            reset_nav, reset_trades = _simulate(annual_windows, selections, daily_lookup, execution_lookup, constraint_lookup, year_dates, initial_cash=1.0, cost_rate=ONE_WAY_COST)
            reset_zero_cost_nav, _ = _simulate(annual_windows, selections, daily_lookup, execution_lookup, constraint_lookup, year_dates, initial_cash=1.0, cost_rate=0.0)
            reset_nav = _attach_zero_cost_counterfactual(reset_nav, reset_zero_cost_nav)
            annual_rows.append({"year": year, "scope": "INDEPENDENT_RESET_FULLY_WITHIN_YEAR", "cohort_count": len(annual_windows), **_nav_metrics(reset_nav, reset_trades)})
    coverage = pd.concat([pd.DataFrame(coverage_rows), pd.DataFrame([{"overall_status": "UNKNOWN_NAV_PRESENT" if nav["nav"].isna().any() else "VALUED", "daily_adj_factor_missing_rows": daily_adj_factor_missing_rows, "execution_missing_vwap_rows": execution_missing_vwap_rows, "stale_mark_days": int(nav["stale_mark_position_count"].sum()), "unknown_listing_status_position_days": int(nav["unknown_listing_status_position_count"].sum()), "unknown_nav_days": int(nav["nav"].isna().sum())}])], ignore_index=True, sort=False)
    resource_budget = pd.DataFrame([{
        "lookup_engine": LOOKUP_ENGINE, **input_row_counts,
        "calendar_days": len(dates), "lookup_build_passes": 5,
        "row_lookup_full_frame_scans": 0,
        "estimated_simulation_lookup_calls": int(len(trades) * 3 + len(nav) * max(1, nav["open_position_count"].max())),
        "frame_copy_policy": "SHALLOW_NORMALIZATION__NO_FULL_KEY_MERGE__DROP_KEY_COLUMNS__NO_SORTED_INDEX_COPY__INDEX_FACTOR_DOMAIN_BY_DATE__RELEASE_PREINDEX_REFS",
        "gross_counterfactual_passes": 1,
        "scalability_contract": "BUILD_UNIQUE_MULTIINDEX_ONCE__NO_PER_ORDER_FULL_FRAME_FILTER__MEMORY_BUDGET_REQUIRED_FOR_FULL_IS",
    }])
    return {"daily_nav": nav, "trades": trades, "monthly_ic": ic, "annual_is_slices": pd.DataFrame(annual_rows), "coverage": coverage, "performance": pd.DataFrame([performance]), "matched_eligible_ew_benchmark": benchmark, "resource_budget": resource_budget}


def _read_frame(path: str, *, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise PortfolioEvaluatorError(f"prepared_input_missing:{source}")
    if source.suffix.lower() == ".parquet":
        filters = None if start is None else [("trade_date", ">=", start), ("trade_date", "<=", end)]
        try:
            return pd.read_parquet(source, filters=filters)
        except Exception as exc:
            raise PortfolioEvaluatorError("prepared_parquet_year_predicate_failed") from exc
    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source)
        if start is not None and "trade_date" in frame:
            dates = _parse_trade_dates(frame["trade_date"]).dt.strftime("%Y-%m-%d")
            frame = frame.loc[dates.between(f"{start[:4]}-01-01", f"{end[:4]}-12-31")]
        return frame
    raise PortfolioEvaluatorError("prepared_inputs_require_csv_or_parquet")


def _assert_explicit_source_is_only(path: str) -> None:
    """Reject an explicitly supplied OOS file before its bounded parquet read.

    The preflight reads only the key column; large value reads below still use
    parquet predicates.  Silently dropping 2025-07-14 would be an OOS leak
    hidden as an IS evaluation, so that file is an input-contract error.
    """
    source = Path(path)
    if not source.is_file():
        raise PortfolioEvaluatorError(f"prepared_input_missing:{source}")
    if source.suffix.lower() == ".parquet":
        dates = pd.read_parquet(source, columns=["trade_date"])["trade_date"]
    elif source.suffix.lower() == ".csv":
        dates = pd.read_csv(source, usecols=["trade_date"])["trade_date"]
    else:
        raise PortfolioEvaluatorError("prepared_inputs_require_csv_or_parquet")
    parsed = _parse_trade_dates(dates)
    if parsed.isna().any() or parsed.dt.date.lt(IS_START).any() or parsed.dt.date.gt(IS_CUTOFF).any():
        raise PortfolioEvaluatorError("prepared_input_outside_frozen_is")


def _split_daily_raw_and_adj(daily_raw_path: str, adj_factor_path: str, calendar_dates: list[str]) -> pd.DataFrame:
    """Read and merge raw daily/adj inputs one calendar year at a time."""
    pieces: list[pd.DataFrame] = []
    for year in sorted({value[:4] for value in calendar_dates}):
        # Prepared MSZQ parquet uses the normalized YYYYMMDD trade-date key.
        start, end = f"{year}0101", f"{year}1231"
        raw, adj = _read_frame(daily_raw_path, start=start, end=end), _read_frame(adj_factor_path, start=start, end=end)
        if "close_unadjusted" not in raw and "close" in raw:
            raw = raw.rename(columns={"close": "close_unadjusted"})
        _require_columns(raw, {"ts_code", "trade_date", "close_unadjusted"}, "daily_raw")
        _require_columns(adj, {"ts_code", "trade_date", "adj_factor"}, "adj_factor")
        pieces.append(raw[["ts_code", "trade_date", "close_unadjusted"]].merge(adj[["ts_code", "trade_date", "adj_factor"]], on=["ts_code", "trade_date"], how="left", validate="one_to_one"))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=["ts_code", "trade_date", "close_unadjusted", "adj_factor"])


def run_cli(report_id: str, output: Path, prepared_inputs: Path) -> dict[str, object]:
    spec = json.loads(prepared_inputs.read_text(encoding="utf-8"))
    required = {"factor_values_path", "measurement_domain_path", "execution_vwap_path", "calendar_path", "complete_months"}
    constraint_path = spec.get("normalized_constraints_path") if isinstance(spec, dict) else None
    constraint_path = constraint_path or (spec.get("v17_constraints_path") if isinstance(spec, dict) else None)
    if not isinstance(spec, dict) or required - set(spec) or not constraint_path or ("daily_prices_path" not in spec and not {"daily_raw_path", "adj_factor_path"}.issubset(spec)):
        raise PortfolioEvaluatorError("prepared_inputs_missing_explicit_paths")
    for key in ("factor_values_path", "measurement_domain_path", "execution_vwap_path", "calendar_path"):
        _assert_explicit_source_is_only(str(spec[key]))
    _assert_explicit_source_is_only(str(constraint_path))
    if "daily_prices_path" in spec:
        _assert_explicit_source_is_only(str(spec["daily_prices_path"]))
    else:
        _assert_explicit_source_is_only(str(spec["daily_raw_path"]))
        _assert_explicit_source_is_only(str(spec["adj_factor_path"]))
    is_start, is_end = IS_START.strftime("%Y%m%d"), IS_CUTOFF.strftime("%Y%m%d")
    # Every large parquet read is predicate-bounded to the frozen IS.  Direct
    # DataFrame entry remains strict and rejects any supplied OOS row.
    calendar = _read_frame(str(spec["calendar_path"]), start=is_start, end=is_end)
    _require_columns(calendar, {"trade_date", "is_open"}, "calendar")
    calendar_dates = _dates(calendar, "calendar")["trade_date"].tolist()
    daily = _read_frame(str(spec["daily_prices_path"]), start=is_start, end=is_end) if "daily_prices_path" in spec else _split_daily_raw_and_adj(str(spec["daily_raw_path"]), str(spec["adj_factor_path"]), calendar_dates)
    constraint_frame = _read_frame(str(constraint_path), start=is_start, end=is_end)
    if "historicalstatus_present" not in constraint_frame.columns and V17_RAW_REQUIRED.issubset(constraint_frame.columns):
        # Existing prepared V17 is raw execution evidence.  Map it in memory;
        # no fake listing-state column is added to the prepared source.
        constraint_frame = normalize_v17_constraints(constraint_frame)
    result = evaluate_from_frames(
        factor_values=_read_frame(str(spec["factor_values_path"]), start=is_start, end=is_end),
        measurement_domain=_read_frame(str(spec["measurement_domain_path"]), start=is_start, end=is_end), daily_prices=daily,
        execution_vwap=_read_frame(str(spec["execution_vwap_path"]), start=is_start, end=is_end),
        normalized_constraints=constraint_frame,
        calendar=calendar, complete_months=spec["complete_months"],
    )
    artifact_dir = output.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, frame in result.items():
        path = artifact_dir / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[key] = str(path)
    nav, trades, ic, coverage = result["daily_nav"], result["trades"], result["monthly_ic"], result["coverage"]
    performance = result["performance"].iloc[0].to_dict()
    resource_budget = result["resource_budget"].iloc[0].to_dict()
    benchmark = result["matched_eligible_ew_benchmark"]
    stale_metadata = _stale_metadata(nav)
    unknown_nav = int(nav["nav"].isna().sum())
    # A flat/no-trade NAV has a mathematically undefined Sharpe: preserve that
    # fact and prevent a success payload from standing in for a full metric set.
    metrics_complete = bool(
        performance["net_valuation_complete"] and performance["gross_valuation_complete"]
        and np.isfinite(performance["net_annualized_daily_sharpe"])
        and np.isfinite(performance["gross_annualized_daily_sharpe"])
    )
    long_side_performance = {
        "metric_period": "daily", "annualization_factor": 252,
        "long_side_annual_return": performance["net_annualized_return"],
        "long_side_annual_volatility": performance["net_annualized_volatility"],
        "long_side_sharpe": performance["net_annualized_daily_sharpe"],
        "long_side_max_drawdown": performance["net_max_drawdown"],
        "long_side_recovery_days": performance["net_recovery_days"],
        "long_side_recovery_status": performance["net_recovery_status"],
        "long_side_recovery_lower_bound_days": performance["net_recovery_lower_bound_days"],
        "long_side_recovery_observation_end": performance["net_recovery_observation_end"],
        "long_side_turnover_mean_daily": performance["turnover_gross_amount"] / max(1, len(nav)),
        "trading_cogs_daily": performance["cost_sum"] / max(1, len(nav)),
        "cost_adjusted_long_side_sharpe": performance["net_annualized_daily_sharpe"],
        "gross_zero_cost_counterfactual_annual_return": performance["gross_annualized_return"],
        "gross_zero_cost_counterfactual_sharpe": performance["gross_annualized_daily_sharpe"],
        "gross_zero_cost_counterfactual_recovery_status": performance["gross_recovery_status"],
        "gross_zero_cost_counterfactual_recovery_lower_bound_days": performance["gross_recovery_lower_bound_days"],
        "gross_zero_cost_counterfactual_recovery_observation_end": performance["gross_recovery_observation_end"],
        "source": {"net": "daily_nav.nav__daily_return__cost_rate_0.003", "gross_zero_cost_counterfactual": "daily_nav.gross_nav__gross_daily_return__independent_cost_rate_0"},
    }
    payload = {"backend": BACKEND_NAME, "status": "success" if metrics_complete and not unknown_nav else "partial", "schema_id": SCHEMA_ID, "report_id": report_id, "authority_effect": AUTHORITY_EFFECT, "evidence_scope": EVIDENCE_SCOPE, "promotion_eligibility": "NOT_AVAILABLE_CANDIDATE_ONLY", "artifact_paths": list(paths.values()), "artifacts": paths, "portfolio_timing_contract": {"signal_time": "D_CLOSE", "entry": "D_PLUS_1_0945_1000_UNADJUSTED_VWAP", "exit": "ENTRY_PLUS_20_TRADING_DAYS_0945_1000_UNADJUSTED_VWAP", "overlap_policy": "CASH_ONLY_SEQUENTIAL_NO_LEVERAGE_SELL_THEN_BUY"}, "cost_model": {"one_way_rate": ONE_WAY_COST, "gross_definition": "INDEPENDENT_SAME_RULES_ZERO_COST_COUNTERFACTUAL", "capacity_conclusion": "NOT_AVAILABLE"}, "limitations": {"security_survival_and_delisting_settlement": "HISTORICAL_STATUS_NOT_COMPLETE__ORDINARY_IS_RESEARCH_ONLY", "capacity": "NOT_EVALUATED", "benchmark": "MATCHED_ELIGIBLE_DOMAIN_EQUAL_WEIGHT_DIAGNOSTIC__NOT_AN_INDEX"}, "ic_summary": {"pearson_ic_mean": ic["pearson_ic"].mean(), "rank_ic_mean": ic["rank_ic"].mean(), "information_ratio": "NOT_EVALUATED", "observation_count": int(ic["pearson_ic"].notna().sum()), "minimum_names": MIN_IC_NAMES}, "performance": performance, "long_side_performance": long_side_performance, "resource_budget": resource_budget, "benchmark_comparison": {"kind": "MATCHED_ELIGIBLE_DOMAIN_EQUAL_WEIGHT_DIAGNOSTIC_NOT_INDEX", "observed_days": int(benchmark["benchmark_nav"].notna().sum()), "final_diagnostic_nav": None if benchmark["benchmark_nav"].dropna().empty else float(benchmark["benchmark_nav"].dropna().iloc[-1])}, "summary": {"final_account": None if nav["nav"].dropna().empty else float(nav["nav"].dropna().iloc[-1]), "unknown_nav_days": unknown_nav, "stale_mark_days": int(nav["stale_mark_position_count"].sum()), "unknown_listing_status_position_days": int(nav["unknown_listing_status_position_count"].sum()), "stale_mark_materiality": stale_metadata, "metrics_complete": metrics_complete}, "coverage": coverage.to_dict(orient="records"), "warnings": ["UNKNOWN_DELISTED_VALUE prevents success" if unknown_nav else "", "Historical security survival/delisting settlement is not complete; ordinary IS research only, not deployable or promotion evidence.", "Costs are a fixed 30bp one-way approximation; no capacity conclusion.", "Matched eligible-domain equal weight is a diagnostic, not an index."], "prepared_inputs_path": str(prepared_inputs)}
    payload["warnings"] = [warning for warning in payload["warnings"] if warning]
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=lambda value: None if pd.isna(value) else float(value) if isinstance(value, np.floating) else int(value) if isinstance(value, np.integer) else str(value)), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")  # Passed by Step4; intentionally not used for discovery.
    parser.add_argument("--prepared-inputs", required=True)
    args = parser.parse_args()
    run_cli(args.report_id, Path(args.output), Path(args.prepared_inputs))


if __name__ == "__main__":
    main()
