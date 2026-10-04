import math
import numpy as np
import pandas as pd
IS_START=pd.Timestamp("2016-01-04")
IS_END=pd.Timestamp("2025-07-11")

def dates(values):
    # Explicitly handle numeric YYYYMMDD, never interpret integers as nanoseconds.
    return pd.DatetimeIndex(pd.to_datetime(pd.Series(values).astype(str), errors="raise")).normalize()


def calendar_windows(calendar):
    c = dates(calendar)
    if c.has_duplicates or not c.is_monotonic_increasing:
        raise ValueError("calendar_not_unique_increasing")
    f = np.flatnonzero(c[:-1].to_period("M") != c[1:].to_period("M"))
    f = [int(i) for i in f if IS_START <= c[i] <= IS_END]
    rows = []
    for k, i in enumerate(f):
        nxt = f[k + 1] if k + 1 < len(f) else None
        entry = c[i + 1] if c[i + 1] <= IS_END else pd.NaT
        end = c[nxt + 1] if nxt is not None and c[nxt + 1] <= IS_END else pd.NaT
        proxy_end = c[i + 20] if i + 20 < len(c) and c[i + 20] <= IS_END else pd.NaT
        rows.append({"signal_date": c[i], "entry_date": entry,
                     "label_end_date": end, "proxy_end_date": proxy_end})
    return pd.DataFrame(rows, columns=["signal_date", "entry_date", "label_end_date", "proxy_end_date"])


def hac_mean(slots):
    """Bartlett lag3, calendar slots kept; pair sums / n_observed**2.

    Equivalent sandwich intercept-only mean variance with missing scores zero
    in calendar slots, NOT compressing gaps or imputing missing observations.
    No finite-sample multiplier. Degenerate SE is unavailable inference.
    """
    x = np.asarray(slots, dtype=float)
    mask = np.isfinite(x)
    n = int(mask.sum())
    if not n:
        return {"n": 0, "mean": None, "se": None, "positive_p": None, "negative_p": None}
    mean = float(x[mask].mean())
    z = np.where(mask, x-mean, 0.)
    meat = float(z@z)
    for lag in range(1, 4):
        meat += 2*(1-lag/4)*float(z[lag:]@z[:-lag])
    se = math.sqrt(max(0., meat))/n
    return {"n": n, "mean": mean, "se": se if se > 0 else None,
            "positive_p": .5*math.erfc(mean/se/math.sqrt(2)) if se > 0 else None,
            "negative_p": .5*math.erfc(-mean/se/math.sqrt(2)) if se > 0 else None,
            "missing_slots": np.flatnonzero(~mask).tolist()}


def upper_tail_targets(frame, pit_count):
    x = frame.loc[np.isfinite(frame.factor_value)]
    if pit_count <= 0:
        raise ValueError("missing_PIT_denominator")
    if len(x) < 30 or len(x)/pit_count < .5 or x.factor_value.nunique() < 2:
        return pd.Series(dtype=float, name="target_weight")
    threshold = np.quantile(x.factor_value, .9, method="linear")
    selected = x.loc[x.factor_value >= threshold, "ts_code"]
    return pd.Series(1/len(selected), index=selected, name="target_weight")


