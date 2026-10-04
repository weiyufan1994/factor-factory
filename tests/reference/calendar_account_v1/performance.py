import numpy as np

def performance(nav):
    """252 exchange sessions/year; sample SD; recovery from worst DD trough.

    Initial cash NAV=1 is included in high-water mark so entry cost is not lost.
    Recovery is sessions after worst trough until prior high is regained; when
    not regained report observed lower bound/right censor rather than252.
    """
    x, ret = nav.nav.to_numpy(float), nav.daily_return.to_numpy(float)
    if not len(x) or not np.isfinite(x).all() or not np.isfinite(ret).all() or (x <= 0).any():
        raise ValueError("incomplete_account_valuation")
    peak = np.maximum.accumulate(np.r_[1., x])[1:]
    dd = x/peak-1
    trough = int(np.argmin(dd))
    recover = np.flatnonzero(x[trough+1:] >= peak[trough])
    recovered = dd[trough] >= 0 or len(recover) > 0
    recovery = 0 if dd[trough] >= 0 else int(recover[0]+1) if len(recover) else None
    sd = np.std(ret, ddof=1) if len(ret) > 1 else np.nan
    sharpe = np.sqrt(252)*ret.mean()/sd if sd > 0 else np.nan
    return {"long_side_annual_return": float(np.prod(1+ret)**(252/len(ret))-1),
            "long_side_annual_volatility": float(sd*np.sqrt(252)),
            "long_side_sharpe": sharpe, "cost_adjusted_long_side_sharpe": sharpe,
            "long_side_max_drawdown": float(dd.min()), "long_side_recovery_days": recovery,
            "long_side_recovery_status": "RECOVERED" if recovered else "NOT_RECOVERED_BY_WINDOW_END",
            "long_side_recovery_lower_bound_days": None if recovered else len(x)-1-trough,
            "long_side_recovery_observation_end": str(nav.trade_date.iloc[-1].date()),
            "long_side_turnover_mean_daily": float(nav.half_L1_turnover.mean()),
            "trading_cogs_daily": float(nav.cost_weight.mean()),
            "drawdown_area_sessions": float(-dd.sum()),
            "metric_period": "daily", "annualization_factor": 252,
            "return_basis": "net_after_explicit_trading_costs"}


