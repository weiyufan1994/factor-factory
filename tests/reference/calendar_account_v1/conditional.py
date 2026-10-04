# Frozen selected pure reference functions; never import the old study.
# Source rs60_evaluator_v1.py SHA256 762636c364306bbcfb992bfdaf4dc52bc22203bc17b3beda87596d7d424bd5fa
import numpy as np
import pandas as pd

CONTROL_NAMES = ["size", "size_square", "value", "volatility", "short_reversal",
                 "momentum", "activity", "low_price", "activity_square",
                 "volatility_square", "activity_volatility_interaction"]

def midrank(x):
    return (pd.Series(x).rank(method="average").to_numpy() - .5) / len(x)

def design_matrix(frame):
    """Rank only after the final regression complete-case intersection."""
    u = {k: midrank(frame[k + "_raw"]) for k in
         ["size", "value", "volatility", "activity", "low_price", "short_reversal", "momentum"]}
    v = {"size": u["size"], "size_square": (u["size"]-.5)**2,
         "value": -u["value"], "volatility": u["volatility"],
         "short_reversal": -u["short_reversal"], "momentum": u["momentum"],
         "activity": u["activity"], "low_price": u["low_price"],
         "activity_square": (u["activity"]-.5)**2,
         "volatility_square": (u["volatility"]-.5)**2,
         "activity_volatility_interaction": (u["activity"]-.5)*(u["volatility"]-.5)}
    return np.column_stack([np.ones(len(frame)), midrank(frame.factor_value), *[v[k] for k in CONTROL_NAMES]])

def monthly_regression(frame):
    required = ["y", "factor_value"] + [k + "_raw" for k in
        ["size", "value", "volatility", "activity", "low_price", "short_reversal", "momentum"]]
    clean = frame.loc[np.isfinite(frame[required]).all(axis=1)].copy()
    result = {"n": len(clean), "beta": np.nan, "status": "insufficient_cases"}
    if clean.ts_code.duplicated().any():
        raise ValueError("regression_duplicate_security")
    if len(clean) < 100:
        return result
    if not clean.score_gate.all() or not clean.varying_signal.all() or clean.factor_value.nunique() < 2:
        return {**result, "status": "no_signal"}
    X, y = design_matrix(clean), clean.y.to_numpy()
    singular = np.linalg.svd(X, compute_uv=False)
    rank = int((singular > singular[0] * 1e-10).sum())
    result.update(singular_values=singular.tolist(), rank=rank,
                  condition_number=float(singular[0]/singular[-1]) if singular[-1] else np.inf)
    if rank != X.shape[1]:
        return {**result, "status": "singular_design"}
    coef = np.linalg.lstsq(X, y, rcond=1e-10)[0]
    X0 = np.delete(X, 1, axis=1)
    residual = y-X@coef
    residual0 = y-X0@np.linalg.lstsq(X0, y, rcond=1e-10)[0]
    return {**result, "status": "accepted", "beta": float(coef[1]),
            "sse_full": float(residual@residual), "sse_controls": float(residual0@residual0),
            "support": clean.ts_code.astype(str).tolist()}
