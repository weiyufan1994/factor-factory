"""Lossless in-memory encoding checks for completed PF/VV engine ledgers."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.mszq_intraday_momentum_pulse import pfvv_monthly_evaluation_v1 as monthly


def _legacy_object_mapping(source: pd.DataFrame) -> pd.DataFrame:
    """The pre-encoding mapping semantics, retained only as a test oracle."""
    mapped = source.copy()
    mapped["engine_source"] = "synthetic_engine"
    mapped["engine_trade_reason"] = source["reason"]
    mapped["portfolio_group"] = "G10"
    buy_mask = mapped["side"].eq("BUY") & mapped["reason"].eq("MONTH_END_TOP_QUINTILE")
    mapped["reason"] = mapped["reason"].mask(buy_mask, "MONTH_END_G10")
    mapped["adapter_trade_reason"] = mapped["reason"]
    mapped["counterfactual_one_way_rate"] = 0.0
    return mapped


def test_completed_trade_ledger_encoding_is_lossless_and_compact() -> None:
    rows = 4_096
    source = pd.DataFrame(
        {
            "trade_date": np.where(np.arange(rows) % 2, "2016-01-12", "2016-01-11"),
            "formation_date": "2015-12-31",
            "ts_code": [f"{index % 32:06d}.SZ" for index in range(rows)],
            "side": np.where(np.arange(rows) % 3, "BUY", "SELL"),
            "status": "FILLED",
            "reason": np.where(
                np.arange(rows) % 3,
                "MONTH_END_TOP_QUINTILE",
                "PRETRADE_BUY_BLOCKED",
            ),
            "gross_amount": np.arange(rows, dtype=float) + 100.0,
            "cost": np.arange(rows, dtype=float) / 1000.0,
        }
    )
    source_before = source.copy(deep=True)
    legacy = _legacy_object_mapping(source)

    mapped = monthly._map_account_trades(
        source,
        account_id="G10",
        engine_source="synthetic_engine",
        counterfactual_rate=0.0,
    )

    # The engine-owned input remains byte-for-byte/value-for-value untouched;
    # numeric columns are not copied merely to encode repeated text.
    pd.testing.assert_frame_equal(source, source_before)
    assert np.shares_memory(source["gross_amount"].to_numpy(), mapped["gross_amount"].to_numpy())
    for column in legacy.columns:
        if pd.api.types.is_numeric_dtype(legacy[column]):
            np.testing.assert_array_equal(mapped[column].to_numpy(), legacy[column].to_numpy())
        else:
            assert mapped[column].astype("string").tolist() == legacy[column].astype("string").tolist()

    assert mapped["trade_date"].dtype.storage == "pyarrow"
    assert mapped["formation_date"].dtype.storage == "pyarrow"
    assert (mapped["trade_date"] < "2016-01-12").sum() == rows // 2
    assert str(mapped["reason"].dtype) == "category"
    assert mapped.loc[mapped["side"].eq("BUY"), "reason"].eq("MONTH_END_G10").all()
    assert mapped.loc[mapped["side"].eq("SELL"), "reason"].eq("PRETRADE_BUY_BLOCKED").all()

    # The relevant baseline is the legacy mapped object ledger, not the raw
    # engine frame (the adapter necessarily adds provenance columns).
    assert mapped.memory_usage(index=True, deep=True).sum() < legacy.memory_usage(index=True, deep=True).sum()
