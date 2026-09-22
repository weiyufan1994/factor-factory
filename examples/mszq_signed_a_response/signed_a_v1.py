"""Pure candidate implementation for the signed-A source extension.

This module deliberately has no file, network, factor-value, or evaluation IO.
It only standardizes the supplied same-day ``pf_daily`` cross-section.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("ts_code", "trade_date", "pf_daily", "baseline_eligible")
STATUS_COLUMNS = (
    "trade_date",
    "status",
    "n_eligible",
    "n_finite_eligible",
    "mean_pf_daily",
    "sample_sd_pf_daily",
)


@dataclass(frozen=True)
class SignedAScoreResult:
    """Ordered row scores plus an auditable date-level computation status."""

    scores: pd.DataFrame
    date_status: pd.DataFrame


def _normalized_dates(values: pd.Series) -> pd.Series:
    normalized: list[str] = []
    for value in values.tolist():
        if not isinstance(value, str) or re.fullmatch(r"\d{8}", value) is None:
            raise ValueError("trade_date must contain only 8-digit YYYYMMDD strings")
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"trade_date contains invalid YYYYMMDD date: {value!r}") from exc
        if parsed.strftime("%Y%m%d") != value:
            raise ValueError(f"trade_date is not canonical YYYYMMDD: {value!r}")
        normalized.append(value)
    return pd.Series(normalized, index=values.index, dtype="string")


def _validate_input(frame: pd.DataFrame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    normalized_dates = _normalized_dates(frame["trade_date"])
    keys = pd.DataFrame({"trade_date": normalized_dates, "ts_code": frame["ts_code"]})
    if keys.isna().any().any() or (keys["ts_code"].astype(str).str.len() == 0).any():
        raise ValueError("ts_code and trade_date keys must be nonmissing")
    if keys.duplicated().any():
        raise ValueError("duplicate (trade_date, ts_code) keys")

    try:
        values = pd.to_numeric(frame["pf_daily"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("pf_daily must be numeric") from exc
    if np.isinf(values.to_numpy()).any():
        raise ValueError("pf_daily must not contain infinity")

    eligibility = frame["baseline_eligible"]
    if eligibility.isna().any() or not all(isinstance(value, (bool, np.bool_)) for value in eligibility):
        raise ValueError("baseline_eligible must contain only nonmissing booleans")
    return normalized_dates


def compute_signed_a_scores(frame: pd.DataFrame) -> SignedAScoreResult:
    """Compute ``score=-z_cs(pf_daily)`` independently for each date.

    The input row order is preserved in ``scores``.  Excluded rows and missing
    values remain NaN.  ``date_status`` is sorted by normalized date and makes
    constant and undersized cross-sections explicit rather than silently
    converting either to tradable rankings.
    """
    normalized_dates = _validate_input(frame)
    values = pd.to_numeric(frame["pf_daily"], errors="raise").astype(float)
    eligible = frame["baseline_eligible"].astype(bool).to_numpy()
    finite = np.isfinite(values.to_numpy())
    score = np.full(len(frame), np.nan, dtype=float)
    status_rows: list[dict[str, Any]] = []

    work = pd.DataFrame(
        {"normalized_date": normalized_dates.to_numpy(), "value": values.to_numpy(),
         "eligible": eligible, "finite": finite}
    )
    for trade_date, group in work.groupby("normalized_date", sort=True):
        eligible_group = group[group["eligible"]]
        finite_group = eligible_group[eligible_group["finite"]]
        n_eligible = len(eligible_group)
        n_finite = len(finite_group)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                mean = float(finite_group["value"].mean()) if n_finite else np.nan
                sample_sd = float(finite_group["value"].std(ddof=1)) if n_finite >= 2 else np.nan
        except FloatingPointError as exc:
            raise ValueError(f"pf_daily mean or sample SD overflow on {trade_date}") from exc
        if (n_finite and not np.isfinite(mean)) or (n_finite >= 2 and not np.isfinite(sample_sd)):
            raise ValueError(f"pf_daily mean or sample SD is non-finite on {trade_date}")
        if n_finite < 2:
            status = "MISSING"
        elif sample_sd == 0.0:
            status = "NONDISCRIMINATING"
            score[finite_group.index] = 0.0
        else:
            status = "OK"
            score[finite_group.index] = -(finite_group["value"].to_numpy() - mean) / sample_sd
        status_rows.append(
            {"trade_date": trade_date, "status": status, "n_eligible": n_eligible,
             "n_finite_eligible": n_finite, "mean_pf_daily": mean,
             "sample_sd_pf_daily": sample_sd}
        )

    scores = pd.DataFrame(
        {"ts_code": frame["ts_code"].to_numpy(copy=True),
         "trade_date": frame["trade_date"].to_numpy(copy=True), "score": score}
    )
    date_status = pd.DataFrame(status_rows, columns=STATUS_COLUMNS)
    return SignedAScoreResult(scores=scores, date_status=date_status)


def compute_factor(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Direct-code adapter returning the Step2 factor-value shape.

    ``date_status`` is attached as a DataFrame attribute so the numerical
    result remains a plain three-column frame and no input object is mutated.
    """
    result = compute_signed_a_scores(daily_df)
    output = result.scores.rename(columns={"score": "factor_value"})
    output.attrs["date_status"] = result.date_status.copy(deep=True)
    return output[["ts_code", "trade_date", "factor_value"]]


__all__ = [
    "REQUIRED_COLUMNS", "STATUS_COLUMNS", "SignedAScoreResult",
    "compute_signed_a_scores", "compute_factor",
]
