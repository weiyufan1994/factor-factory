from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor_factory.data_access.daily_basic import (
    daily_basic_partition_path,
    get_daily_basic_with_profile,
    write_daily_basic_parquet_partitions,
)
from factor_factory.data_access.paths import LocalTusharePaths
from factor_factory.data_api import fetch_data_api_dataset


def _paths_with_daily_basic(tmp_path: Path) -> LocalTusharePaths:
    root = tmp_path / "raw_tushare"
    daily_basic_dir = root / "行情数据" / "daily_basic_incremental"
    daily_basic_dir.mkdir(parents=True)
    return LocalTusharePaths(
        root=root,
        daily_csv=root / "行情数据" / "daily.csv",
        adj_factor_csv=root / "行情数据" / "adj_factor.csv",
        daily_basic_dir=daily_basic_dir,
        trade_cal_csv=root / "基础数据" / "trade_cal.csv",
        stock_basic_csv=root / "基础数据" / "stock_basic.csv",
        stock_st_csv=root / "基础数据" / "stock_st.csv",
        stock_st_daily_csv=root / "基础数据" / "stock_st_daily_20160101_current.csv",
        source_label="test",
    )


def _write_daily_basic_csv(paths: LocalTusharePaths, trade_date: str = "20200102") -> None:
    partition = paths.daily_basic_dir / f"trade_date={trade_date}"
    partition.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 1.0, "total_mv": 100.0},
            {"ts_code": "000002.SZ", "trade_date": trade_date, "turnover_rate": 2.0, "total_mv": 200.0},
            {"ts_code": "000003.SZ", "trade_date": trade_date, "turnover_rate": 3.0, "total_mv": 300.0},
        ]
    ).to_csv(partition / f"daily_basic_{trade_date}.csv", index=False)


def test_symbol_filtered_daily_basic_fetch_does_not_write_shared_full_universe_cache(tmp_path):
    paths = _paths_with_daily_basic(tmp_path)
    _write_daily_basic_csv(paths)
    parquet_root = tmp_path / "daily_basic_cache"

    frame, profile = get_daily_basic_with_profile(
        start="20200102",
        end="20200102",
        symbols=["000001.SZ"],
        columns=["ts_code", "trade_date", "turnover_rate"],
        paths=paths,
        parquet_root=parquet_root,
    )

    assert frame["ts_code"].tolist() == ["000001.SZ"]
    assert profile["cache_status"] == "csv_symbol_filtered_no_shared_cache_write"
    assert not daily_basic_partition_path(parquet_root, "20200102").exists()


def test_full_universe_daily_basic_fetch_rebuilds_polluted_tiny_cache(tmp_path, monkeypatch):
    paths = _paths_with_daily_basic(tmp_path)
    _write_daily_basic_csv(paths)
    parquet_root = tmp_path / "daily_basic_cache"
    monkeypatch.setenv("FACTORFORGE_DAILY_BASIC_FULL_UNIVERSE_MIN_TICKERS", "2")

    write_daily_basic_parquet_partitions(
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20200102",
                    "turnover_rate": 1.0,
                    "total_mv": 100.0,
                }
            ]
        ),
        root=parquet_root,
    )

    frame, profile = get_daily_basic_with_profile(
        start="20200102",
        end="20200102",
        symbols=None,
        columns=["ts_code", "trade_date", "turnover_rate"],
        paths=paths,
        parquet_root=parquet_root,
    )

    assert set(frame["ts_code"]) == {"000001.SZ", "000002.SZ", "000003.SZ"}
    assert profile["cache_status"] == "backfilled_from_csv"
    rebuilt = pd.read_parquet(daily_basic_partition_path(parquet_root, "20200102"))
    assert rebuilt["ts_code"].nunique() == 3


def test_daily_basic_fetch_can_use_clean_daily_local_parquet(tmp_path, monkeypatch):
    clean_daily = tmp_path / "daily_clean.parquet"
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20200102", "turnover_rate": 1.0},
            {"ts_code": "000002.SZ", "trade_date": "20200102", "turnover_rate": 2.0},
        ]
    ).to_parquet(clean_daily, index=False)
    monkeypatch.setenv("FACTORFORGE_CLEAN_DAILY_PARQUET", str(clean_daily))

    result = fetch_data_api_dataset(
        "daily_basic",
        start="20200102",
        end="20200102",
        fields=["turnover_rate"],
        universe="a_share_all",
    )

    assert result.status == "ready"
    assert result.frame["turnover_rate"].tolist() == [1.0, 2.0]
    assert result.to_metadata()["source"]["access_mode"] == "local_clean_daily_parquet_warm_cache"
