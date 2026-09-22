"""Candidate-only IS evaluation calendar for the MSZQ intraday pulse.

This module contains no data access, execution, cost, or authority logic.  It
only maps explicitly supplied trading dates and month-completeness attestations
to the frozen evaluation timing contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime
from typing import Iterable, Sequence


IS_START = date(2016, 1, 4)
IS_CUTOFF = date(2025, 7, 11)
ENTRY_WINDOW = ("09:45", "10:00")
EXIT_WINDOW = ENTRY_WINDOW
HOLDING_TRADING_DAYS = 20


class CalendarContractError(ValueError):
    """Raised when the supplied calendar cannot support a deterministic IS map."""


@dataclass(frozen=True)
class EvaluationWindow:
    """One month-end signal and its point-in-time evaluation window."""

    formation_date: date
    entry_date: date | None
    exit_date: date | None
    entry_window: tuple[str, str]
    exit_window: tuple[str, str]
    holding_trading_days: int
    status: str


def _as_date(value: date | datetime | str, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CalendarContractError(f"{field} contains invalid ISO date: {value!r}") from exc
    raise CalendarContractError(f"{field} must contain date, datetime, or ISO date values")


def _normalize_dates(values: Iterable[date | datetime | str], field: str) -> list[date]:
    normalized = [_as_date(value, field) for value in values]
    if len(set(normalized)) != len(normalized):
        raise CalendarContractError(f"{field} contains duplicate dates")
    return sorted(normalized)


def _month_key(value: date | str) -> str:
    return value if isinstance(value, str) else value.strftime("%Y-%m")


def build_evaluation_windows(
    calendar: Sequence[date | datetime | str],
    signal_dates: Sequence[date | datetime | str],
    *,
    complete_months: Iterable[str],
    cutoff: date | datetime | str = IS_CUTOFF,
) -> tuple[EvaluationWindow, ...]:
    """Build frozen month-end IS windows from a complete trading-day calendar.

    ``complete_months`` is intentionally required: a date list ending in the
    middle of a month cannot prove that the observed last date is that month's
    formation date.  A signal is valid only when it equals the last supplied
    trading day of an explicitly complete month.  Missing +20 exits are marked
    ``IMMATURE``; no post-cutoff date is ever inferred or read.

    The caller must supply a genuinely complete trading-calendar segment for
    the requested scope, including exchange holidays and suspensions as
    applicable.  A complete segment is not by itself a claim that Full-IS has
    been completed.  This function only sorts and validates supplied dates; it
    never infers missing dates or holidays.
    """

    cutoff_date = _as_date(cutoff, "cutoff")
    if cutoff_date < IS_START or cutoff_date > IS_CUTOFF:
        raise CalendarContractError(
            f"cutoff must be within [{IS_START.isoformat()}, {IS_CUTOFF.isoformat()}]"
        )
    dates = _normalize_dates(calendar, "calendar")
    if not dates:
        raise CalendarContractError("calendar must not be empty")
    if any(value < IS_START for value in dates):
        raise CalendarContractError(
            f"calendar cannot contain dates before the IS start {IS_START.isoformat()}"
        )
    if any(value > cutoff_date for value in dates):
        raise CalendarContractError("calendar contains dates after the IS cutoff")

    month_set = set(complete_months)
    for month in month_set:
        if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
            raise CalendarContractError("complete_months must contain YYYY-MM strings")
        try:
            date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise CalendarContractError(f"complete_months contains invalid month: {month!r}") from exc
    date_set = set(dates)
    by_month: dict[str, list[date]] = {}
    for value in dates:
        by_month.setdefault(_month_key(value), []).append(value)
    undeclared_months = sorted(month_set - set(by_month))
    if undeclared_months:
        raise CalendarContractError(
            f"complete_months contains month absent from calendar: {undeclared_months[0]}"
        )
    cutoff_month = _month_key(cutoff_date)
    if cutoff_month in month_set and cutoff_date.day != monthrange(cutoff_date.year, cutoff_date.month)[1]:
        raise CalendarContractError(
            f"cutoff month {cutoff_month} is not complete at cutoff {cutoff_date.isoformat()}"
        )
    # Partial/unattested months are allowed in the input calendar, but can
    # never silently become formation months.
    signals = _normalize_dates(signal_dates, "signal_dates")
    if any(value < IS_START for value in signals):
        raise CalendarContractError(
            f"signal_dates cannot contain dates before the IS start {IS_START.isoformat()}"
        )
    if any(value > cutoff_date for value in signals):
        raise CalendarContractError("signal_dates contains a date after the IS cutoff")

    windows: list[EvaluationWindow] = []
    for signal in signals:
        if signal not in date_set:
            raise CalendarContractError(f"signal date is absent from calendar: {signal.isoformat()}")
        month = _month_key(signal)
        if month not in month_set:
            raise CalendarContractError(
                f"signal month is not explicitly complete: {month}"
            )
        formation = by_month[month][-1]
        if signal != formation:
            raise CalendarContractError(
                f"signal date {signal.isoformat()} is not the complete month-end formation date "
                f"{formation.isoformat()}"
            )
        formation_index = dates.index(formation)
        entry_index = formation_index + 1
        exit_index = formation_index + 1 + HOLDING_TRADING_DAYS
        entry = dates[entry_index] if entry_index < len(dates) else None
        exit_date = dates[exit_index] if exit_index < len(dates) else None
        if entry is not None and entry > cutoff_date:
            entry = None
        if exit_date is not None and exit_date > cutoff_date:
            exit_date = None
        status = "MATURE" if entry is not None and exit_date is not None else "IMMATURE"
        windows.append(
            EvaluationWindow(
                formation_date=formation,
                entry_date=entry,
                exit_date=exit_date,
                entry_window=ENTRY_WINDOW,
                exit_window=EXIT_WINDOW,
                holding_trading_days=HOLDING_TRADING_DAYS,
                status=status,
            )
        )
    return tuple(windows)


__all__ = [
    "CalendarContractError",
    "EvaluationWindow",
    "HOLDING_TRADING_DAYS",
    "IS_CUTOFF",
    "build_evaluation_windows",
]
