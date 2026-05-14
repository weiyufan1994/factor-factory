from __future__ import annotations

import numpy as np
import pandas as pd


def cs_rank(series: pd.Series, frame: pd.DataFrame) -> pd.Series:
    if 'trade_date' in frame.columns:
        return series.groupby(frame['trade_date']).rank(method='average', pct=True)
    return series.rank(method='average', pct=True)


def ts_sum(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).sum())


def ts_mean(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())


def ts_std(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).std())


def ts_rank(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(
            lambda values: pd.Series(values).rank(method='average', pct=True).iloc[-1],
            raw=False,
        )
    )


def ts_min(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).min())


def ts_max(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(lambda s: s.rolling(window, min_periods=window).max())


def ts_argmin(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmin(values)) + 1.0, raw=True)
    )


def ts_argmax(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmax(values)) + 1.0, raw=True)
    )


def ts_delta(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).diff(window)


def ts_delay(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).shift(window)


def rolling_corr(left: pd.Series, right: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    tmp = pd.DataFrame({'ts_code': frame['ts_code'], 'left': left, 'right': right})
    return tmp.groupby('ts_code', sort=False, group_keys=False).apply(
        lambda g: g['left'].rolling(window, min_periods=window).corr(g['right'])
    )


def rolling_cov(left: pd.Series, right: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    tmp = pd.DataFrame({'ts_code': frame['ts_code'], 'left': left, 'right': right})
    return tmp.groupby('ts_code', sort=False, group_keys=False).apply(
        lambda g: g['left'].rolling(window, min_periods=window).cov(g['right'])
    )


def cs_scale(series: pd.Series, frame: pd.DataFrame) -> pd.Series:
    denom = series.abs().groupby(frame['trade_date']).transform('sum')
    return series / denom.replace(0, np.nan)


def signed_power(left: pd.Series, right) -> pd.Series:
    return np.sign(left) * (np.abs(left) ** right)
