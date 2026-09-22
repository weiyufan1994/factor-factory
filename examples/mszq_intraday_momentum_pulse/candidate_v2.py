"""Candidate-only EVENT_U measurement successor.

This is a narrow, self-contained successor for the event-U projection, not a
paper replication of the source report's PF/VV composite and not a formal run.
It performs no I/O, network, OOS, persistence, or return evaluation.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


ARTIFACT_STATUS = "CANDIDATE_ONLY"
AUTHORITY_EFFECT = "NONE"
PRIMARY_PROFILE_ID = "EVENT_Z3_H30_LOOKBACK20_V2_MEASUREMENT_BOUNDARY"
DEFAULT_EVENT_PARAMS = {
    "lookback_dates": 20,
    "minimum_history_dates": 15,
    "threshold": 3.0,
    "response_horizon": 30,
    "epsilon": 1.0e-12,
}
CANONICAL_BAR_COUNT = 240
CANONICAL_TIMES = tuple(
    pd.date_range("2000-01-01 09:31", "2000-01-01 11:30", freq="min").strftime("%H:%M:%S")
) + tuple(
    pd.date_range("2000-01-01 13:01", "2000-01-01 15:00", freq="min").strftime("%H:%M:%S")
)
EVENT_COVERAGE_STATES = frozenset(
    {
        "INSUFFICIENT_HISTORY",
        "INVALID_BASELINE",
        "PARTIAL_COVERAGE",
        "VALID_NO_EVENT",
        "VALID_WITH_EVENT",
    }
)


def _robust_z(values: pd.Series) -> pd.Series:
    """Median/MAD z-score with a deterministic nonconstant MAD-zero fallback.

    Population standard deviation is used only when MAD is zero but observed
    finite values differ.  It preserves ordinal cross-sectional information;
    truly constant finite inputs remain zero and missing inputs remain missing.
    """
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    finite = numeric.dropna()
    if finite.empty:
        return pd.Series(np.nan, index=values.index, dtype=float)
    median = finite.median()
    mad = (finite - median).abs().median()
    if np.isfinite(mad) and mad > 0.0:
        return (numeric - median) / (1.4826 * mad)
    if finite.nunique(dropna=True) == 1:
        return pd.Series(np.where(numeric.notna(), 0.0, np.nan), index=values.index, dtype=float)
    scale = finite.std(ddof=0)
    if not np.isfinite(scale) or scale <= 0.0:
        raise RuntimeError("nonconstant MAD-zero values require positive population scale")
    return (numeric - median) / scale


def _prior_median_mad(values: pd.Series, lookback: int, minimum: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return strictly-prior baseline, MAD, and finite prior-observation count."""
    shifted = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).shift(1)
    count = shifted.rolling(lookback, min_periods=1).count()
    median = shifted.rolling(lookback, min_periods=minimum).median()

    def mad_value(window: np.ndarray) -> float:
        window = window[np.isfinite(window)]
        if window.size < minimum:
            return np.nan
        center = float(np.median(window))
        return float(np.median(np.abs(window - center)))

    mad = shifted.rolling(lookback, min_periods=minimum).apply(mad_value, raw=True)
    return median, mad, count


def _event_outputs(canonical: pd.DataFrame, config: dict[str, Any] | None = None) -> pd.DataFrame:
    """Compute frozen EVENT_U only when every search slot has a valid baseline.

    No event is a valid zero only after all slots have mature, positive-MAD
    baselines.  Missing history, zero/invalid baseline, or partial coverage is
    diagnostic missingness, never silently converted to U=0.
    """
    config = dict(DEFAULT_EVENT_PARAMS if config is None else config)
    required = {"ts_code", "trade_date", "bar_time", "session_ordinal", "vol", "log_return"}
    missing = required - set(canonical.columns)
    if missing:
        raise ValueError(f"canonical is missing columns: {sorted(missing)}")
    lookback = int(config["lookback_dates"])
    minimum = int(config["minimum_history_dates"])
    threshold = float(config["threshold"])
    horizon = int(config["response_horizon"])
    epsilon = float(config["epsilon"])
    if (lookback, minimum, threshold, horizon, epsilon) != (20, 15, 3.0, 30, 1.0e-12):
        raise ValueError("EVENT_U v2 uses only the frozen Z3/H30/lookback20/min15 profile")

    work = canonical.copy()
    if work.empty or work[["ts_code", "trade_date", "bar_time", "session_ordinal"]].isna().any().any():
        raise ValueError("nonempty input with complete identity/time fields required")
    work["ts_code"] = work["ts_code"].astype(str)
    work["trade_date"] = work["trade_date"].astype(str)
    work["session_ordinal"] = pd.to_numeric(work["session_ordinal"], errors="raise")
    if (~np.isfinite(work["session_ordinal"])).any() or (work["session_ordinal"] % 1 != 0).any():
        raise ValueError("session ordinal must be a finite integer")
    if work.duplicated(["ts_code", "trade_date", "session_ordinal"]).any():
        raise ValueError("duplicate stock-date canonical session slot")
    work["vol"] = pd.to_numeric(work["vol"], errors="coerce")
    work["log_return"] = pd.to_numeric(work["log_return"], errors="coerce")
    if (~np.isfinite(work["vol"])).any() or (work["vol"] < 0.0).any():
        raise ValueError("vol must be finite and nonnegative")
    if (~np.isfinite(work["log_return"])).any():
        raise ValueError("log_return must be finite")
    work = work.sort_values(["ts_code", "trade_date", "session_ordinal", "bar_time"], kind="mergesort").reset_index(drop=True)
    expected_slots = set(range(CANONICAL_BAR_COUNT))
    for key, day in work.groupby(["ts_code", "trade_date"], sort=False):
        if len(day) != CANONICAL_BAR_COUNT or set(day["session_ordinal"].astype(int)) != expected_slots:
            raise ValueError(f"incomplete canonical 240-bar session: {key}")
        if tuple(day["bar_time"].astype(str)) != CANONICAL_TIMES:
            raise ValueError(f"canonical clock/ordinal mismatch: {key}")
    work["log_volume"] = np.log1p(pd.to_numeric(work["vol"], errors="coerce"))
    baseline_parts: list[pd.Series] = []
    mad_parts: list[pd.Series] = []
    count_parts: list[pd.Series] = []
    for _, indexes in work.groupby(["ts_code", "bar_time"], sort=False).indices.items():
        loc = np.asarray(indexes, dtype=int)
        median, mad, count = _prior_median_mad(work.loc[loc, "log_volume"].reset_index(drop=True), lookback, minimum)
        for values, parts in ((median, baseline_parts), (mad, mad_parts), (count, count_parts)):
            values.index = loc
            parts.append(values)
    work["volume_baseline"] = pd.concat(baseline_parts).sort_index().reindex(work.index)
    raw_mad = pd.concat(mad_parts).sort_index().reindex(work.index)
    work["prior_history_count"] = pd.concat(count_parts).sort_index().reindex(work.index)
    work["volume_scale"] = 1.4826 * raw_mad
    work["baseline_mature"] = work["prior_history_count"] >= minimum
    work["baseline_valid"] = work["baseline_mature"] & np.isfinite(work["log_volume"]) & np.isfinite(work["volume_baseline"]) & np.isfinite(work["volume_scale"]) & (work["volume_scale"] > 0.0)
    work["volume_surprise"] = np.where(
        work["baseline_valid"], (work["log_volume"] - work["volume_baseline"]) / work["volume_scale"], np.nan
    )
    work["event_candidate"] = (work["volume_surprise"] >= threshold) & (work["log_return"] != 0.0)

    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), indexes in work.groupby(["ts_code", "trade_date"], sort=False).indices.items():
        loc = np.asarray(indexes, dtype=int)
        day = work.loc[loc]
        # The final horizon bars cannot initiate a retained event. Their
        # baseline state must not downgrade an otherwise complete search day.
        search = day.iloc[: CANONICAL_BAR_COUNT - horizon]
        mature = search["baseline_mature"].to_numpy(dtype=bool)
        valid = search["baseline_valid"].to_numpy(dtype=bool)
        if not mature.any():
            state = "INSUFFICIENT_HISTORY"
        elif not mature.all():
            state = "PARTIAL_COVERAGE"
        elif not valid.any():
            state = "INVALID_BASELINE"
        elif not valid.all():
            state = "PARTIAL_COVERAGE"
        else:
            state = "VALID_NO_EVENT"
        retained: list[int] = []
        if state == "VALID_NO_EVENT":
            returns = day["log_return"].to_numpy(dtype=float)
            candidates = day["event_candidate"].to_numpy(dtype=bool)
            blocked_through = -1
            for pos in np.flatnonzero(candidates):
                pos = int(pos)
                if pos <= blocked_through or pos + horizon >= len(day):
                    continue
                retained.append(pos)
                blocked_through = pos + horizon
            if retained:
                immediate = np.abs(returns[np.asarray(retained, dtype=int)])
                signed_post = np.asarray([np.sign(returns[pos]) * returns[pos + 1:pos + horizon + 1].sum() for pos in retained])
                residual = np.maximum(0.0, immediate + signed_post)
                event_u = float(residual.sum() / (immediate.sum() + epsilon))
                state = "VALID_WITH_EVENT"
                contrast_pool = np.ones(len(returns), dtype=bool)
                contrast_pool[np.asarray(retained, dtype=int)] = False
                other_abs = np.abs(returns[contrast_pool])
                contrast = float(immediate.mean() - other_abs.mean()) if other_abs.size else np.nan
                immediate_mean, post_mean = float(immediate.mean()), float(signed_post.mean())
                residual_sum, immediate_sum = float(residual.sum()), float(immediate.sum())
            else:
                event_u, contrast, immediate_mean, post_mean = 0.0, np.nan, np.nan, np.nan
                residual_sum, immediate_sum = 0.0, 0.0
        else:
            event_u = contrast = immediate_mean = post_mean = residual_sum = immediate_sum = np.nan
        rows.append({
            "ts_code": ts_code, "trade_date": trade_date, "event_coverage_state": state,
            "event_search_slot_count": int(len(search)), "event_mature_baseline_count": int(mature.sum()),
            "event_valid_baseline_count": int(valid.sum()), "event_missing_baseline_count": int((~valid).sum()),
            "event_count": len(retained) if state.startswith("VALID_") else None, "event_u": event_u,
            "event_k0_identity_abs_mean": immediate_mean,
            "event_h1_h_signed_response_mean": post_mean,
            "event_abs_displacement_same_day_raw_contrast": contrast,
            "event_residual_pressure_sum": residual_sum,
            "event_immediate_abs_sum": immediate_sum,
        })
    return pd.DataFrame(rows)


def project_factor(event_rows: pd.DataFrame) -> pd.DataFrame:
    """Same-date cross-sectional projection; only valid EVENT_U rows rank."""
    required = {"ts_code", "trade_date", "event_u", "event_coverage_state"}
    if missing := required - set(event_rows.columns):
        raise ValueError(f"event rows are missing columns: {sorted(missing)}")
    out = event_rows.copy()
    valid = out["event_coverage_state"].isin(["VALID_NO_EVENT", "VALID_WITH_EVENT"])
    out["factor_value"] = np.nan
    out.loc[valid, "factor_value"] = -out.loc[valid].groupby("trade_date", sort=False)["event_u"].transform(_robust_z)
    out["artifact_status"] = ARTIFACT_STATUS
    out["authority_effect"] = AUTHORITY_EFFECT
    return out
