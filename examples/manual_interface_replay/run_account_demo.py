"""Four-session account oracle. All values are invented test data, not quotes.

Hand calculation, fixed before executing the API:
  1010 cash -> buy 100 units at 10, fee 10 -> 1000 marked equity.
  Scheduled exit is suspended -> retain 100 units, last mark 10.
  Sell at 12, fee 12 -> 1188 cash. Total fees 22.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from factor_factory.portfolio_api import backtest


def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    index = pd.MultiIndex.from_product([dates, ["000001.SZ"]], names=["datetime", "instrument"])
    factor = pd.DataFrame({"factor_value": [1.0]}, index=index[:1])
    prices = pd.DataFrame({
        "execution_price": [10.0, 10.0, np.nan, 12.0],
        "mark_price": [10.0, 10.0, np.nan, 12.0],
    }, index=index)
    constraints = pd.DataFrame({
        "can_buy": [True, True, False, True],
        "can_sell": [True, True, False, True],
        "is_suspended": [False, False, True, False],
    }, index=index)
    options = dict(calendar=dates, formation_dates=dates[:1], holding_period=1,
                   entry_offset=1, initial_cash=1010.0, one_way_cost=0.01)
    result = backtest(factor, prices=prices, constraints=constraints, **options)

    # Compare the entire path, not just the final return.
    daily = pd.DataFrame(result["daily"])
    np.testing.assert_allclose(daily["equity"], [1010.0, 1000.0, 1000.0, 1188.0])
    np.testing.assert_allclose(daily["cash"], [1010.0, 0.0, 0.0, 1188.0], atol=1e-12)
    np.testing.assert_allclose(daily["nav"], np.array([1010.0, 1000.0, 1000.0, 1188.0]) / 1010)
    assert result["metrics"]["fees_paid"]["value"] == 22.0
    filled = [x for x in result["trades"] if x["status"] == "FILLED"]
    assert [x["side"] for x in filled] == ["BUY", "SELL"]
    assert filled[0]["units"] == 100.0
    assert filled[0]["fee"] == 10.0 and filled[1]["fee"] == 12.0

    # If the entry cannot be bought, keep cash; do not invent a later fill.
    no_buy = constraints.copy()
    no_buy.loc[(dates[1], "000001.SZ"), "can_buy"] = False
    blocked = backtest(factor, prices=prices, constraints=no_buy, **options)
    np.testing.assert_allclose([x["equity"] for x in blocked["daily"]], [1010.0] * 4)
    assert not any(x["status"] == "FILLED" for x in blocked["trades"])

    daily.to_csv(output_dir / "account_daily.csv", index=False)
    pd.DataFrame(result["trades"]).to_csv(output_dir / "account_trades.csv", index=False)
    pd.DataFrame(result["positions"]).to_csv(output_dir / "account_positions.csv", index=False)
    (output_dir / "account_results.json").write_text(
        json.dumps({"suspended_exit": result, "blocked_entry": blocked},
                   indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    print("Hand-calculated account path matched exactly (within floating-point tolerance).")
    print(daily.to_string(index=False))
    print(pd.DataFrame(result["trades"]).to_string(index=False))
    print("Total return:", result["metrics"]["total_return"])
    print("Blocked entry: four sessions of 1010 cash, no filled trade.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    main(parser.parse_args().output_dir)
