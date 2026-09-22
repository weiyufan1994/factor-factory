"""Pure-local PF/VV monthly portfolio schedule and explicit-engine adapter.

This is deliberately an example-layer adapter, not another backtest engine.
It owns the frozen monthly calendar and the pre-declared ten-group assignment;
an execution engine is supplied explicitly by the caller for input validation,
order simulation, and the independent 20-trading-day IC labels.  It performs
no I/O, data discovery, network access, or implicit module import.
"""

from __future__ import annotations

from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime
from numbers import Integral
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd


ENTRY_WINDOW = ("09:45", "10:00")
EXIT_WINDOW = ENTRY_WINDOW
LABEL_HOLDING_TRADING_DAYS = 20
GROUP_COUNT = 10
ONE_WAY_COST = 0.003
TIE_RULE = "FACTOR_ASCENDING_AVERAGE_RANK__EQUAL_VALUES_STAY_TOGETHER__FIXED_PRE_RETURN"
IS_START = date(2016, 1, 4)
IS_CUTOFF = date(2025, 7, 11)


class MonthlyEvaluationError(ValueError):
    """Raised for an incomplete local calendar, group, or engine contract."""


@dataclass(frozen=True)
class EvaluationWindow:
    """Duck-compatible window consumed by the supplied legacy execution engine."""

    formation_date: date
    entry_date: date | None
    exit_date: date | None
    entry_window: tuple[str, str]
    exit_window: tuple[str, str]
    holding_trading_days: int | None
    status: str


@dataclass(frozen=True)
class MonthlyTenGroups:
    """Pre-return factor groups keyed by formation date and group id."""

    members: Mapping[str, Mapping[str, pd.DataFrame]]
    counts: pd.DataFrame
    status_by_formation: Mapping[str, str]
    tie_rule: str = TIE_RULE


class ExecutionEngine(Protocol):
    """The intentionally small private-function surface this adapter reuses."""

    ONE_WAY_COST: float

    def _normalize_inputs(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]: ...
    def _date_lookup(self, frame: pd.DataFrame) -> pd.DataFrame: ...
    def _validate_factor_domain(self, factor_by_date: pd.DataFrame, measurement_by_date: pd.DataFrame) -> None: ...
    def _stock_day_lookup(self, frame: pd.DataFrame) -> pd.DataFrame: ...
    def _simulate(self, *args: Any, **kwargs: Any) -> tuple[pd.DataFrame, pd.DataFrame]: ...
    def _attach_zero_cost_counterfactual(self, net_nav: pd.DataFrame, zero_cost_nav: pd.DataFrame) -> pd.DataFrame: ...
    def _nav_metrics(self, nav: pd.DataFrame, trades: pd.DataFrame) -> dict[str, object]: ...
    def _monthly_ic(self, *args: Any, **kwargs: Any) -> pd.DataFrame: ...


def _as_date(value: date | datetime | str | int, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Integral) and not isinstance(value, bool):
        value = str(int(value))
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y%m%d").date() if value.isdigit() and len(value) == 8 else date.fromisoformat(value)
        except ValueError as exc:
            raise MonthlyEvaluationError(f"{field}_invalid_iso_date:{value!r}") from exc
    raise MonthlyEvaluationError(f"{field}_must_contain_dates")


def _resolved_cutoff(cutoff: date | datetime | str | int | None) -> date:
    cutoff_date = IS_CUTOFF if cutoff is None else _as_date(cutoff, "cutoff")
    if cutoff_date < IS_START or cutoff_date > IS_CUTOFF:
        raise MonthlyEvaluationError(f"cutoff_outside_frozen_is:{cutoff_date.isoformat()}")
    return cutoff_date


def _dates(calendar: Sequence[date | datetime | str | int], cutoff: date | datetime | str | int | None) -> list[date]:
    dates = sorted(_as_date(value, "calendar") for value in calendar)
    if not dates:
        raise MonthlyEvaluationError("calendar_empty")
    if len(dates) != len(set(dates)):
        raise MonthlyEvaluationError("calendar_duplicate_dates")
    cutoff_date = _resolved_cutoff(cutoff)
    if any(value < IS_START for value in dates):
        raise MonthlyEvaluationError("calendar_before_frozen_is")
    if any(value > cutoff_date for value in dates):
        raise MonthlyEvaluationError("calendar_after_cutoff")
    return dates


def _complete_month_sequence(complete_months: Iterable[str], by_month: Mapping[str, list[date]]) -> list[str]:
    months = sorted(set(complete_months))
    if not months:
        raise MonthlyEvaluationError("complete_months_empty")
    for month in months:
        try:
            parsed = datetime.strptime(month, "%Y-%m")
        except (TypeError, ValueError) as exc:
            raise MonthlyEvaluationError(f"complete_month_invalid:{month!r}") from exc
        if parsed.strftime("%Y-%m") != month:
            raise MonthlyEvaluationError(f"complete_month_invalid:{month!r}")
        if month not in by_month:
            raise MonthlyEvaluationError(f"complete_month_absent_from_calendar:{month}")
    for prior, current in zip(months, months[1:]):
        prior_year, prior_month = map(int, prior.split("-"))
        expected = f"{prior_year + (prior_month == 12):04d}-{1 if prior_month == 12 else prior_month + 1:02d}"
        if current != expected:
            # Mapping January straight to March would silently replace the
            # promised next-month rebalance with a two-month hold.
            raise MonthlyEvaluationError(f"complete_months_not_consecutive:{prior}:{current}")
    return months


def _calendar_context(
    calendar: Sequence[date | datetime | str | int], complete_months: Iterable[str], cutoff: date | datetime | str | int | None,
) -> tuple[list[date], list[str], dict[str, list[date]]]:
    dates = _dates(calendar, cutoff)
    by_month: dict[str, list[date]] = {}
    for value in dates:
        by_month.setdefault(value.strftime("%Y-%m"), []).append(value)
    months = _complete_month_sequence(complete_months, by_month)
    cutoff_date = _resolved_cutoff(cutoff)
    cutoff_month = cutoff_date.strftime("%Y-%m")
    if cutoff_month in months and (
        cutoff_date.day != monthrange(cutoff_date.year, cutoff_date.month)[1]
        or by_month[cutoff_month][-1] != cutoff_date
    ):
        raise MonthlyEvaluationError(f"cutoff_month_not_complete:{cutoff_month}")
    # A later allowed cutoff does not extend the supplied calendar.  For the
    # terminal month, require an observed month boundary: either dates extend
    # into the next month, or the final supplied day is the calendar month end.
    # When month end is a holiday, include the next month's first trading day
    # in the explicit calendar instead of guessing its missing tail here.
    terminal = dates[-1]
    if terminal.strftime("%Y-%m") in months and terminal.day != monthrange(terminal.year, terminal.month)[1]:
        raise MonthlyEvaluationError(f"calendar_terminal_month_not_proven_complete:{terminal:%Y-%m}")
    return dates, months, by_month


def build_monthly_rebalance_windows(
    calendar: Sequence[date | datetime | str | int], *, complete_months: Iterable[str], cutoff: date | datetime | str | int | None = None,
) -> tuple[EvaluationWindow, ...]:
    """Build month-end signal windows whose exit is the next rebalance entry.

    The final declared formation is intentionally ``IMMATURE``: its next
    rebalance has not been attested, so it cannot enter a completed portfolio
    account.  No fixed-session holding interval is substituted.
    """

    dates, months, by_month = _calendar_context(calendar, complete_months, cutoff)
    index_by_date = {value: index for index, value in enumerate(dates)}
    formations = [by_month[month][-1] for month in months]
    entries: list[date | None] = []
    for formation in formations:
        next_index = index_by_date[formation] + 1
        entries.append(dates[next_index] if next_index < len(dates) else None)

    windows: list[EvaluationWindow] = []
    for index, formation in enumerate(formations):
        entry = entries[index]
        exit_date = entries[index + 1] if index + 1 < len(entries) else None
        status = "MATURE" if entry is not None and exit_date is not None else "IMMATURE"
        windows.append(EvaluationWindow(
            formation_date=formation, entry_date=entry, exit_date=exit_date,
            entry_window=ENTRY_WINDOW, exit_window=EXIT_WINDOW,
            holding_trading_days=None, status=status,
        ))
    return tuple(windows)


def build_twenty_trading_day_label_windows(
    calendar: Sequence[date | datetime | str | int], *, complete_months: Iterable[str], cutoff: date | datetime | str | int | None = None,
) -> tuple[EvaluationWindow, ...]:
    """Build separate, fixed-20-trading-day IC label windows only.

    These windows must never be passed to the cash portfolio simulation.
    """

    dates, months, by_month = _calendar_context(calendar, complete_months, cutoff)
    index_by_date = {value: index for index, value in enumerate(dates)}
    windows: list[EvaluationWindow] = []
    for month in months:
        formation = by_month[month][-1]
        entry_index = index_by_date[formation] + 1
        exit_index = entry_index + LABEL_HOLDING_TRADING_DAYS
        entry = dates[entry_index] if entry_index < len(dates) else None
        exit_date = dates[exit_index] if exit_index < len(dates) else None
        status = "MATURE" if entry is not None and exit_date is not None else "IMMATURE"
        windows.append(EvaluationWindow(
            formation_date=formation, entry_date=entry, exit_date=exit_date,
            entry_window=ENTRY_WINDOW, exit_window=EXIT_WINDOW,
            holding_trading_days=LABEL_HOLDING_TRADING_DAYS, status=status,
        ))
    return tuple(windows)


def build_monthly_ten_groups(
    factor_values: pd.DataFrame, measurement_domain: pd.DataFrame, windows: Iterable[EvaluationWindow],
) -> MonthlyTenGroups:
    """Assign exactly ten factor groups before any price/return/execution input.

    Factor values use ascending average-rank bins.  Equal values therefore stay
    together; an all-tied cross section may leave groups empty and is explicitly
    ``NOT_EVALUABLE_EMPTY_GROUPS`` rather than being ticker-split into a fake
    ten-group result.  The rule is fixed before an execution engine receives a
    selection; future returns and execution eligibility cannot choose members.
    """

    required_factor = {"ts_code", "trade_date", "factor_value"}
    required_domain = {"ts_code", "trade_date"}
    if not required_factor.issubset(factor_values.columns):
        raise MonthlyEvaluationError("factor_values_missing_required_columns")
    if not required_domain.issubset(measurement_domain.columns):
        raise MonthlyEvaluationError("measurement_domain_missing_required_columns")
    factor = factor_values.loc[:, ["ts_code", "trade_date", "factor_value"]].copy()
    domain = measurement_domain.loc[:, ["ts_code", "trade_date"]].copy()
    factor["trade_date"] = _normalize_trade_date_series(factor["trade_date"], "factor_trade_date")
    domain["trade_date"] = _normalize_trade_date_series(domain["trade_date"], "measurement_domain_trade_date")
    factor["factor_value"] = pd.to_numeric(factor["factor_value"], errors="coerce")
    if factor.duplicated(["ts_code", "trade_date"]).any() or domain.duplicated(["ts_code", "trade_date"]).any():
        raise MonthlyEvaluationError("factor_or_domain_duplicate_key")

    members: dict[str, dict[str, pd.DataFrame]] = {}
    status_by_formation: dict[str, str] = {}
    count_rows: list[dict[str, object]] = []
    for window in windows:
        formation = window.formation_date.isoformat()
        day_domain = domain.loc[domain["trade_date"].eq(formation), ["ts_code"]]
        observed = factor.loc[factor["trade_date"].eq(formation), ["ts_code", "factor_value"]]
        day = day_domain.merge(observed, on="ts_code", how="left", validate="one_to_one")
        valid = day.loc[np.isfinite(day["factor_value"])].sort_values(
            ["factor_value", "ts_code"], ascending=[True, True], kind="mergesort",
        ).reset_index(drop=True)
        if valid.empty:
            valid["group_number"] = pd.Series(dtype="int64")
        else:
            average_rank = valid["factor_value"].rank(method="average", ascending=True)
            valid["group_number"] = np.ceil(average_rank * GROUP_COUNT / len(valid)).astype(int)
        grouped: dict[str, pd.DataFrame] = {}
        count_row: dict[str, object] = {
            "formation_date": formation, "measurement_domain_count": int(len(day_domain)),
            "finite_factor_count": int(len(valid)), "tie_rule": TIE_RULE,
        }
        for group_number in range(1, GROUP_COUNT + 1):
            group_id = f"G{group_number:02d}"
            group = valid.loc[valid["group_number"].eq(group_number), ["ts_code", "factor_value"]].copy()
            grouped[group_id] = group
            count_row[group_id] = int(len(group))
        status_by_formation[formation] = "EVALUABLE" if all(int(count_row[f"G{number:02d}"]) > 0 for number in range(1, GROUP_COUNT + 1)) else "NOT_EVALUABLE_EMPTY_GROUPS"
        count_row["ten_group_status"] = status_by_formation[formation]
        members[formation] = grouped
        count_rows.append(count_row)
    return MonthlyTenGroups(
        members=members, counts=pd.DataFrame(count_rows), status_by_formation=status_by_formation,
        tie_rule=TIE_RULE,
    )


def _normalize_trade_date_series(values: pd.Series, field: str) -> pd.Series:
    """Normalize ISO, compact YYYYMMDD strings/ints, and pandas timestamps."""

    text = values.astype(str).str.strip()
    compact = text.str.fullmatch(r"\d{8}")
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    if (~compact).any():
        parsed.loc[~compact] = pd.to_datetime(values.loc[~compact], errors="coerce")
    if parsed.isna().any():
        raise MonthlyEvaluationError(f"{field}_invalid")
    return parsed.dt.strftime("%Y-%m-%d")


def _require_engine(engine: ExecutionEngine) -> None:
    required = (
        "_normalize_inputs", "_date_lookup", "_validate_factor_domain", "_stock_day_lookup",
        "_simulate", "_attach_zero_cost_counterfactual", "_nav_metrics", "_monthly_ic",
    )
    missing = [name for name in required if not callable(getattr(engine, name, None))]
    if missing:
        raise MonthlyEvaluationError("execution_engine_missing:" + ",".join(missing))
    try:
        engine_cost = float(engine.ONE_WAY_COST)
    except (AttributeError, TypeError, ValueError) as exc:
        raise MonthlyEvaluationError("execution_engine_missing_one_way_cost") from exc
    if engine_cost != ONE_WAY_COST:
        raise MonthlyEvaluationError(f"execution_engine_cost_not_frozen_30bp:{engine_cost}")


def _map_account_trades(
    source: pd.DataFrame, *, account_id: str, engine_source: str,
    counterfactual_rate: float | None = None,
) -> pd.DataFrame:
    """Losslessly encode a completed ledger; never change simulator inputs.

    Numeric buffers are shared read-only with the returned engine frame.  Text
    columns get independent dictionary encodings, so long repeated provenance
    strings do not occupy one Python/string buffer per transaction.
    """
    mapped = source.copy(deep=False)
    mapped["engine_source"] = engine_source
    mapped["engine_trade_reason"] = source["reason"]
    mapped["portfolio_group"] = account_id
    buy_mask = mapped["side"].eq("BUY") & mapped["reason"].eq("MONTH_END_TOP_QUINTILE")
    mapped["reason"] = mapped["reason"].mask(buy_mask, f"MONTH_END_{account_id}")
    mapped["adapter_trade_reason"] = mapped["reason"]
    if counterfactual_rate is not None:
        mapped["counterfactual_one_way_rate"] = counterfactual_rate
    for column in ("trade_date", "formation_date"):
        if column in mapped.columns:
            # Preserve ordinary lexical date comparisons (including scalar
            # dates absent from the ledger); unordered categories cannot.
            mapped[column] = mapped[column].astype("string[pyarrow]")
    for column in (
        "ts_code", "side", "status", "reason",
        "engine_source", "engine_trade_reason", "portfolio_group", "adapter_trade_reason",
    ):
        if column in mapped.columns:
            mapped[column] = mapped[column].astype("category")
    return mapped


def _account(
    engine: ExecutionEngine, windows: Iterable[EvaluationWindow], selections: Mapping[str, pd.DataFrame],
    daily_lookup: pd.DataFrame, execution_lookup: pd.DataFrame, constraint_lookup: pd.DataFrame,
    calendar_dates: list[str], *, account_id: str, engine_source: str,
) -> dict[str, object]:
    net_nav, trades = engine._simulate(
        windows, dict(selections), daily_lookup, execution_lookup, constraint_lookup, calendar_dates,
        cost_rate=ONE_WAY_COST,
    )
    mapped_trades = _map_account_trades(trades, account_id=account_id, engine_source=engine_source)
    del trades
    gross_nav, gross_trades = engine._simulate(
        windows, dict(selections), daily_lookup, execution_lookup, constraint_lookup, calendar_dates,
        cost_rate=0.0,
    )
    mapped_gross_trades = _map_account_trades(
        gross_trades, account_id=account_id, engine_source=engine_source, counterfactual_rate=0.0,
    )
    del gross_trades
    nav = engine._attach_zero_cost_counterfactual(net_nav, gross_nav)
    return {
        "daily_nav": nav,
        "trades": mapped_trades,
        "gross_trades": mapped_gross_trades,
        "performance": engine._nav_metrics(nav, mapped_trades),
        "cost_model": {"net_one_way_rate": ONE_WAY_COST, "gross_one_way_rate": 0.0, "gross_definition": "INDEPENDENT_SAME_RULES_ZERO_COST_COUNTERFACTUAL"},
    }


def _diagnostic_spread(group_accounts: Mapping[str, Mapping[str, object]]) -> pd.DataFrame:
    """Return G10 minus G01 daily-return diagnostic, never a short account."""

    top = group_accounts["G10"]["daily_nav"]
    bottom = group_accounts["G01"]["daily_nav"]
    if not isinstance(top, pd.DataFrame) or not isinstance(bottom, pd.DataFrame):
        raise MonthlyEvaluationError("group_account_daily_nav_missing")
    merged = top[["trade_date", "daily_return"]].merge(
        bottom[["trade_date", "daily_return"]], on="trade_date", how="inner", suffixes=("_g10", "_g01"), validate="one_to_one",
    )
    merged["g10_minus_g01_daily_return"] = merged["daily_return_g10"] - merged["daily_return_g01"]
    merged["diagnostic_only"] = True
    return merged


def evaluate_monthly_groups_from_normalized(
    *,
    factor_values: pd.DataFrame,
    measurement_domain: pd.DataFrame,
    calendar_dates: Sequence[date | datetime | str | int],
    daily_lookup: Any,
    execution_lookup: Any,
    constraint_lookup: Any,
    complete_months: Iterable[str],
    execution_engine: ExecutionEngine,
    retain_account_ids: Iterable[str] | None = None,
    account_sink: Callable[[str, Mapping[str, object]], None] | None = None,
) -> dict[str, object]:
    """Evaluate already-normalized PF/VV inputs with supplied engine lookups.

    This is the single monthly evaluation kernel.  The full-frame compatibility
    route and the bounded lookup-store route both arrive here after the frozen
    engine has normalised its own inputs.  In particular this function does not
    reimplement order simulation, selection, valuation, or IC calculation.

    ``retain_account_ids`` is an explicit memory boundary for callers whose
    engine produces large order ledgers.  Every account is still simulated by
    the supplied engine; unretained accounts are offered once to
    ``account_sink`` and then released.  The default retains the historical
    complete result shape.  A bounded caller must retain G01 and G10 because
    their spread remains a required diagnostic.
    """

    _require_engine(execution_engine)
    factors = factor_values
    measurement = measurement_domain
    calendar_dates = list(calendar_dates)
    if not calendar_dates:
        raise MonthlyEvaluationError("calendar_empty")
    complete_months = tuple(complete_months)
    portfolio_windows = build_monthly_rebalance_windows(calendar_dates, complete_months=complete_months, cutoff=calendar_dates[-1])
    label_windows = build_twenty_trading_day_label_windows(calendar_dates, complete_months=complete_months, cutoff=calendar_dates[-1])
    groups = build_monthly_ten_groups(factors, measurement, portfolio_windows)
    factor_by_date, measurement_by_date = execution_engine._date_lookup(factors), execution_engine._date_lookup(measurement)
    execution_engine._validate_factor_domain(factor_by_date, measurement_by_date)
    engine_source = str(getattr(execution_engine, "__name__", type(execution_engine).__name__))
    monthly_ic = execution_engine._monthly_ic(factor_by_date, daily_lookup, execution_lookup, label_windows)
    mature_formations = {window.formation_date.isoformat() for window in portfolio_windows if window.status == "MATURE"}
    non_evaluable = [formation for formation, status in groups.status_by_formation.items() if formation in mature_formations and status != "EVALUABLE"]
    evaluable_formations = sorted(mature_formations - set(non_evaluable))
    if not evaluable_formations:
        return {
            "status": "NOT_EVALUABLE_EMPTY_GROUPS",
            "engine_source": engine_source,
            "portfolio_windows": portfolio_windows,
            "label_windows": label_windows,
            "groups": groups,
            "group_accounts": {},
            "account_summaries": {},
            "benchmark": None,
            "monthly_ic": monthly_ic,
            "contracts": {
                "portfolio_timing": "MONTH_END_SIGNAL__NEXT_TRADING_DAY_0945_1000_VWAP__NEXT_REBALANCE_SAME_WINDOW_EXIT",
                "label_timing": "INDEPENDENT_ENTRY_PLUS_20_TRADING_DAYS_0945_1000_VWAP",
                "group_count": GROUP_COUNT, "tie_rule": TIE_RULE,
                "selection_uses_returns": False, "researcher_reconstruction_not_author_disclosure": True,
                "non_evaluable_mature_formations": non_evaluable,
            },
        }

    status = "PARTIAL_EVALUABLE" if non_evaluable else "EVALUABLE"
    all_account_ids = {*(f"G{number:02d}" for number in range(1, GROUP_COUNT + 1)), "BENCHMARK_ALL_TEN_GROUPS"}
    retained_ids = all_account_ids if retain_account_ids is None else {str(value) for value in retain_account_ids}
    unknown_retained = retained_ids - all_account_ids
    if unknown_retained:
        raise MonthlyEvaluationError("retain_account_ids_unknown:" + ",".join(sorted(unknown_retained)))
    if retain_account_ids is not None and not {"G01", "G10"}.issubset(retained_ids):
        raise MonthlyEvaluationError("retain_account_ids_must_include_g01_g10")

    def finalize_account(account_id: str, account: dict[str, object]) -> tuple[dict[str, object] | None, dict[str, object]]:
        account["evaluation_status"] = status
        account["non_evaluable_mature_formations"] = non_evaluable
        account["cash_only_non_signal_formations"] = non_evaluable
        nav = account.get("daily_nav")
        trades = account.get("trades")
        gross_trades = account.get("gross_trades")
        summary = {
            "account_id": account_id,
            "daily_nav_rows": int(len(nav)) if isinstance(nav, pd.DataFrame) else None,
            "net_trade_rows": int(len(trades)) if isinstance(trades, pd.DataFrame) else None,
            "gross_trade_rows": int(len(gross_trades)) if isinstance(gross_trades, pd.DataFrame) else None,
            "performance": dict(account.get("performance") or {}),
        }
        if account_sink is not None:
            account_sink(account_id, account)
        return (account if account_id in retained_ids else None), summary

    group_accounts: dict[str, dict[str, object]] = {}
    account_summaries: dict[str, dict[str, object]] = {}
    for group_number in range(1, GROUP_COUNT + 1):
        group_id = f"G{group_number:02d}"
        selections = {
            formation: members[group_id] if formation not in non_evaluable else members[group_id].iloc[0:0].copy()
            for formation, members in groups.members.items()
        }
        account = _account(
            execution_engine, portfolio_windows, selections, daily_lookup, execution_lookup, constraint_lookup,
            calendar_dates, account_id=group_id, engine_source=engine_source,
        )
        retained, summary = finalize_account(group_id, account)
        account_summaries[group_id] = summary
        if retained is not None:
            group_accounts[group_id] = retained
    benchmark_selections = {
        formation: (
            pd.concat([members[f"G{number:02d}"] for number in range(1, GROUP_COUNT + 1)], ignore_index=True)
            if formation not in non_evaluable else members["G01"].iloc[0:0].copy()
        )
        for formation, members in groups.members.items()
    }
    benchmark_account = _account(
        execution_engine, portfolio_windows, benchmark_selections, daily_lookup, execution_lookup, constraint_lookup,
        calendar_dates, account_id="BENCHMARK_ALL_TEN_GROUPS", engine_source=engine_source,
    )
    benchmark, benchmark_summary = finalize_account("BENCHMARK_ALL_TEN_GROUPS", benchmark_account)
    account_summaries["BENCHMARK_ALL_TEN_GROUPS"] = benchmark_summary
    return {
        "status": status,
        "engine_source": engine_source,
        "portfolio_windows": portfolio_windows,
        "label_windows": label_windows,
        "groups": groups,
        "group_accounts": group_accounts,
        "account_summaries": account_summaries,
        "benchmark": benchmark,
        "diagnostic_spread": _diagnostic_spread(group_accounts),
        "monthly_ic": monthly_ic,
        "contracts": {
            "portfolio_timing": "MONTH_END_SIGNAL__NEXT_TRADING_DAY_0945_1000_VWAP__NEXT_REBALANCE_SAME_WINDOW_EXIT",
            "label_timing": "INDEPENDENT_ENTRY_PLUS_20_TRADING_DAYS_0945_1000_VWAP",
            "group_count": GROUP_COUNT,
            "tie_rule": TIE_RULE,
            "selection_uses_returns": False,
            "cash_policy": "INDEPENDENT_CASH_ONLY_NO_SHORT",
            "preferred_long_group": "G10",
            "g10_minus_g01": "DIAGNOSTIC_ONLY__NOT_A_SHORT_ACCOUNT",
            "researcher_reconstruction_not_author_disclosure": True,
            "non_evaluable_mature_formations": non_evaluable,
            "cash_only_non_signal_formations": non_evaluable,
        },
    }


def evaluate_monthly_groups(
    *, factor_values: pd.DataFrame, measurement_domain: pd.DataFrame, daily_prices: pd.DataFrame,
    execution_vwap: pd.DataFrame, normalized_constraints: pd.DataFrame, calendar: pd.DataFrame,
    complete_months: Iterable[str], execution_engine: ExecutionEngine,
) -> dict[str, object]:
    """Full-frame compatibility route through the shared monthly kernel.

    The frozen execution engine owns normalisation and all three stock-day
    lookups.  This wrapper intentionally performs no evaluation work beyond
    preparing those existing engine inputs.
    """

    _require_engine(execution_engine)
    factors, measurement, daily, execution, constraints, calendar_dates = execution_engine._normalize_inputs(
        factor_values, measurement_domain, daily_prices, execution_vwap, normalized_constraints, calendar,
    )
    return evaluate_monthly_groups_from_normalized(
        factor_values=factors,
        measurement_domain=measurement,
        calendar_dates=calendar_dates,
        daily_lookup=execution_engine._stock_day_lookup(daily),
        execution_lookup=execution_engine._stock_day_lookup(execution),
        constraint_lookup=execution_engine._stock_day_lookup(constraints),
        complete_months=complete_months,
        execution_engine=execution_engine,
    )


__all__ = [
    "ENTRY_WINDOW", "EXIT_WINDOW", "GROUP_COUNT", "IS_CUTOFF", "IS_START", "LABEL_HOLDING_TRADING_DAYS", "ONE_WAY_COST", "TIE_RULE",
    "EvaluationWindow", "ExecutionEngine", "MonthlyEvaluationError", "MonthlyTenGroups",
    "build_monthly_rebalance_windows", "build_monthly_ten_groups", "build_twenty_trading_day_label_windows",
    "evaluate_monthly_groups", "evaluate_monthly_groups_from_normalized",
]
