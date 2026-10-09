"""Numeric helpers shared by the derived-state kernels."""

import numpy as _factorforge_np
import pandas as _factorforge_pd


def _factorforge_date_key(_frame):
    _out = _frame.copy()
    _out["trade_date"] = _out["trade_date"].astype(str).str.replace("-", "", regex=False).str.slice(0, 8)
    return _out


def _factorforge_z_by_day(_frame, _col):
    if _col not in _frame.columns:
        return _factorforge_pd.Series(_factorforge_np.nan, index=_frame.index)
    _values = _factorforge_pd.to_numeric(_frame[_col], errors="coerce")
    _g = _values.groupby(_frame["trade_date"], sort=False)
    _mean = _g.transform("mean")
    _std = _g.transform("std").replace(0, _factorforge_np.nan)
    return ((_values - _mean) / _std).replace([_factorforge_np.inf, -_factorforge_np.inf], _factorforge_np.nan)


def _factorforge_positive(_series):
    return _factorforge_pd.to_numeric(_series, errors="coerce").clip(lower=0.0)

