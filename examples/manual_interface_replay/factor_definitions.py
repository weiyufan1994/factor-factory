"""Handwritten, synthetic interface demonstration — not a proposed alpha.

Statistic: for each instrument, the two-observation trailing arithmetic mean
of (close - open). Price unit is CNY; result is CNY. Window includes the current
observation. First observation is NaN, not zero. No labels or future rows enter
compute(). The fixed demonstration has every exchange date for every stock.
"""
from collections.abc import Mapping

import pandas as pd

from factor_factory.factors import FundamentalFactor, PriceVolumeFactor
from factor_factory.formula import parse_formula
from factor_factory.formula.evaluator import evaluate_formula_frame


class MeanIntradaySpread(PriceVolumeFactor):
    """Direct-code route: mean(close - open, window), including today's close."""

    name = "synthetic_mean_intraday_spread"
    input_columns = {"daily_df": ("ts_code", "trade_date", "open", "close")}

    def __init__(self, window: int = 2):
        if isinstance(window, bool) or not isinstance(window, int) or window < 1:
            raise ValueError("window must be a positive integer")
        super().__init__(window=window)

    def compute(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        # 1. Copy only needed columns; never change the shared input frame.
        data = inputs["daily_df"][["ts_code", "trade_date", "open", "close"]].copy()
        data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        # 2. The entire mathematical object: price difference, then trailing mean.
        spread = data["close"] - data["open"]
        window = self.parameters["window"]
        values = spread.groupby(data["ts_code"], sort=False).transform(
            lambda stock: stock.rolling(window, min_periods=window).mean()
        )
        # 3. Common output only. BaseFactor.run validates and canonicalizes keys.
        return data[["ts_code", "trade_date"]].assign(factor_value=values)


class HybridMeanIntradaySpread(MeanIntradaySpread):
    """Same object: handwritten spread, registered rolling-mean operator."""

    name = "synthetic_hybrid_mean_intraday_spread"

    def compute(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        data = inputs["daily_df"][["ts_code", "trade_date", "open", "close"]].copy()
        data["spread"] = data["close"] - data["open"]
        ir = parse_formula(f"mean(spread, {self.parameters['window']})",
                           list(data.columns), raise_on_error=True)
        return evaluate_formula_frame(ir, data)


class PointInTimeEarningsYield(FundamentalFactor):
    """Example only: PIT earnings / market cap, both in the same currency unit.

    ``fundamentals`` must already be aligned to the date on which the earnings
    was observable. This class does not turn report periods into availability
    dates, construct TTM from quarters, or forward-fill restated future values.
    Zero/nonpositive market cap yields NaN; negative earnings remain negative.
    """

    name = "pit_earnings_yield_example"
    input_columns = {"fundamentals": (
        "ts_code", "trade_date", "earnings_ttm_cny", "market_cap_cny",
    )}

    def compute(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        data = inputs["fundamentals"]
        denominator = data.market_cap_cny.where(data.market_cap_cny > 0)
        values = data.earnings_ttm_cny / denominator
        return data[["ts_code", "trade_date"]].copy().assign(factor_value=values)


# The common stage runtime may load this instance directly. A human can instead
# instantiate MeanIntradaySpread(window=2) and call it with named DataFrames.
FACTOR = MeanIntradaySpread(window=2)
