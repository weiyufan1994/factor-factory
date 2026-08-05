from __future__ import annotations

import math

import pandas as pd
import pytest

from factor_factory.data_access.step4 import build_forward_return_frame


def test_calendar_aligned_forward_returns_drop_suspended_label_paths() -> None:
    calendar = [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
    ]
    rows = [
        {"ts_code": "A", "trade_date": date, "close": close}
        for date, close in zip(calendar, [10.0, 11.0, 12.0, 13.0, 14.0])
    ]
    rows.extend(
        [
            {"ts_code": "B", "trade_date": "2024-01-02", "close": 20.0},
            {"ts_code": "B", "trade_date": "2024-01-04", "close": 22.0},
            {"ts_code": "B", "trade_date": "2024-01-05", "close": 23.0},
            {"ts_code": "B", "trade_date": "2024-01-08", "close": 24.0},
        ]
    )
    rows.extend(
        [
            {"ts_code": "C", "trade_date": "2024-01-02", "close": 30.0},
            {"ts_code": "C", "trade_date": "2024-01-03", "close": 31.0},
            {"ts_code": "C", "trade_date": "2024-01-05", "close": 33.0},
            {"ts_code": "C", "trade_date": "2024-01-08", "close": 34.0},
        ]
    )

    result = build_forward_return_frame(
        pd.DataFrame(rows),
        return_col=None,
        entry_offset=1,
        exit_offset=2,
        include_label_path=True,
        calendar_dates=calendar,
    ).set_index(["ts_code", "trade_date"])

    uninterrupted = result.loc[("A", "2024-01-02")]
    assert uninterrupted["label_start_date"] == "20240103"
    assert uninterrupted["label_end_date"] == "20240104"
    assert uninterrupted["label_start_price"] == 11.0
    assert uninterrupted["label_end_price"] == 12.0
    assert uninterrupted["future_return_1d"] == pytest.approx(12.0 / 11.0 - 1.0)

    suspended = result.loc[("B", "2024-01-02")]
    assert suspended["label_start_date"] == "20240103"
    assert suspended["label_end_date"] == "20240104"
    assert math.isnan(suspended["label_start_price"])
    assert math.isnan(suspended["future_return_1d"])

    resumed = result.loc[("B", "2024-01-04")]
    assert resumed["label_start_date"] == "20240105"
    assert resumed["label_end_date"] == "20240108"
    assert resumed["future_return_1d"] == pytest.approx(24.0 / 23.0 - 1.0)

    missing_exit = result.loc[("C", "2024-01-02")]
    assert missing_exit["label_start_date"] == "20240103"
    assert missing_exit["label_end_date"] == "20240104"
    assert missing_exit["label_start_price"] == 31.0
    assert math.isnan(missing_exit["label_end_price"])
    assert math.isnan(missing_exit["future_return_1d"])

    calendar_edge = result.loc[("A", "2024-01-05")]
    assert calendar_edge["label_start_date"] == "20240108"
    assert pd.isna(calendar_edge["label_end_date"])
    assert math.isnan(calendar_edge["future_return_1d"])


def test_calendar_aligned_forward_returns_require_canonical_dates() -> None:
    frame = pd.DataFrame(
        [
            {"ts_code": "A", "trade_date": "2024-01-02", "close": 10.0},
            {"ts_code": "A", "trade_date": "2024-01-03", "close": 11.0},
            {"ts_code": "A", "trade_date": "2024-01-04", "close": 12.0},
        ]
    )

    with pytest.raises(ValueError, match="sorted and unique"):
        build_forward_return_frame(
            frame,
            return_col=None,
            entry_offset=1,
            exit_offset=2,
            calendar_dates=["2024-01-03", "2024-01-02", "2024-01-04"],
        )

    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique instrument/date"):
        build_forward_return_frame(
            duplicated,
            return_col=None,
            entry_offset=1,
            exit_offset=2,
            calendar_dates=["2024-01-02", "2024-01-03", "2024-01-04"],
        )
