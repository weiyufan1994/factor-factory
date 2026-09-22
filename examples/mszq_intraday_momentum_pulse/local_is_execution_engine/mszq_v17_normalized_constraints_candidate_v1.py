"""Pure V17-to-portfolio constraint mapping for the local-IS evaluator.

V17 supplies pre-trade execution evidence, not a historical listing master.
Accordingly, absence of a separate status input is represented as UNKNOWN,
never as an inferred ``is_delisted=False`` or ``LISTED`` assertion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


SCHEMA_ID = "mszq_v17_normalized_constraints_candidate_v1"
RAW_REQUIRED = frozenset({
    "ts_code", "trade_date", "st_new_buy_blocked", "pretrade_buy_blocked",
    "pretrade_sell_blocked", "is_st_asof_trade", "up_limit", "down_limit",
    "constraint_complete", "unknown_reason", "delisting_execution_policy",
})
LISTING_STATES = frozenset({"LISTED", "DELISTING", "DELISTED", "NOT_LISTED", "UNKNOWN"})


class V17ConstraintMappingError(ValueError):
    """Raised when the explicit V17 input cannot support a safe mapping."""


def _closed_bool(value: object, field: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool) and int(value) in (0, 1):
        return bool(value)
    raise V17ConstraintMappingError(f"v17_invalid_boolean:{field}")


def _require(frame: pd.DataFrame, columns: frozenset[str], label: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise V17ConstraintMappingError(f"{label}_dataframe_required")
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise V17ConstraintMappingError(f"{label}_missing_columns:{','.join(missing)}")
    if frame.columns.has_duplicates or frame[["ts_code", "trade_date"]].duplicated().any():
        raise V17ConstraintMappingError(f"{label}_duplicate_stock_day")


def normalize_v17_constraints(
    v17: pd.DataFrame, *, historical_status: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Map the actual V17 API fields into the evaluator's normalized interface.

    ``historical_status`` is optional and must be affirmative evidence, with
    ``listing_status`` per stock-day.  Without it the output preserves
    ``listing_status=UNKNOWN`` and ``historicalstatus_present=False``.  Price
    presence and ordinary non-ST observations are deliberately not used to
    infer listing status.
    """
    _require(v17, RAW_REQUIRED, "v17")
    out = v17.copy(deep=True)
    if out["ts_code"].isna().any() or out["ts_code"].astype(str).eq("").any():
        raise V17ConstraintMappingError("v17_invalid_ts_code")
    out["ts_code"] = out["ts_code"].astype(str)
    for column in (
        "st_new_buy_blocked", "pretrade_buy_blocked", "pretrade_sell_blocked",
        "is_st_asof_trade", "constraint_complete",
    ):
        out[column] = out[column].map(lambda value, name=column: _closed_bool(value, name))
    for column in ("up_limit", "down_limit"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    complete = out["constraint_complete"]
    invalid_complete_limits = complete & (
        ~np.isfinite(out["up_limit"]) | ~np.isfinite(out["down_limit"])
        | (out["up_limit"] <= 0) | (out["down_limit"] <= 0)
        | (out["down_limit"] > out["up_limit"])
    )
    if invalid_complete_limits.any():
        raise V17ConstraintMappingError("v17_complete_limit_reference_invalid")
    out["unknown_reason"] = out["unknown_reason"].fillna("").astype(str)
    out["delisting_execution_policy"] = out["delisting_execution_policy"].fillna("").astype(str)
    out["listing_status"] = "UNKNOWN"
    out["historicalstatus_present"] = False
    out["delist_cash_settlement_unadjusted"] = np.nan
    if historical_status is not None:
        _require(historical_status, frozenset({"ts_code", "trade_date", "listing_status"}), "historical_status")
        status = historical_status.copy(deep=True)
        status["ts_code"] = status["ts_code"].astype(str)
        if not status["listing_status"].isin(LISTING_STATES - {"UNKNOWN"}).all():
            raise V17ConstraintMappingError("historical_status_invalid_listing_status")
        status["historicalstatus_present"] = True
        columns = ["ts_code", "trade_date", "listing_status", "historicalstatus_present"]
        if "delist_cash_settlement_unadjusted" in status:
            status["delist_cash_settlement_unadjusted"] = pd.to_numeric(
                status["delist_cash_settlement_unadjusted"], errors="coerce"
            )
            columns.append("delist_cash_settlement_unadjusted")
        out = out.drop(columns=["listing_status", "historicalstatus_present", "delist_cash_settlement_unadjusted"]).merge(
            status[columns], on=["ts_code", "trade_date"], how="left", validate="one_to_one"
        )
        out["listing_status"] = out["listing_status"].fillna("UNKNOWN")
        out["historicalstatus_present"] = out["historicalstatus_present"].fillna(False).astype(bool)
        if "delist_cash_settlement_unadjusted" not in out:
            out["delist_cash_settlement_unadjusted"] = np.nan
    return out[[
        "ts_code", "trade_date", "constraint_complete", "st_new_buy_blocked",
        "pretrade_buy_blocked", "pretrade_sell_blocked", "is_st_asof_trade",
        "up_limit", "down_limit", "unknown_reason", "delisting_execution_policy",
        "historicalstatus_present", "listing_status", "delist_cash_settlement_unadjusted",
    ]]


__all__ = ["LISTING_STATES", "RAW_REQUIRED", "SCHEMA_ID", "V17ConstraintMappingError", "normalize_v17_constraints"]
