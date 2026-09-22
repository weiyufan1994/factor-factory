# Daily Data Policy

This repository uses one shared daily-data hygiene policy for the clean daily base layer and downstream Step 3A / Step 4 evaluation.

## Default Rules

The shared policy is implemented in `factor_factory.data_access.get_clean_daily(...)` and materialized into the shared clean layer by `scripts/build_clean_daily_layer.py`.

Defaults:

- price adjustment: forward-adjusted using `adj_factor.csv`
- drop Beijing-exchange instruments (`.BJ` / `market=北交所`)
- drop ST windows using `stock_st.csv`
- drop listings younger than 60 trading days using `stock_basic.csv` + `trade_cal.csv`
- drop suspended rows where `vol <= 0` or `amount <= 0`
- drop closing limit-up / limit-down rows

## Why This Exists

The policy prevents Step 4 grouped backtests from being polluted by:

- unadjusted split / capital-change jumps
- BJ / OTC-style legacy histories
- ST special-treatment periods
- newly listed stocks with unstable early behavior
- suspended rows that are not tradable
- closing limit-up / limit-down rows that are not realistically executable

## Operational Rule

Factor implementations should not re-implement daily cleaning ad hoc.

Instead:

1. The heavy daily cleaning pass should run in the dedicated workflow: `python3 scripts/build_clean_daily_layer.py`.
2. Step 3A should only slice report-scoped inputs from that shared clean layer.
3. Step 4 should consume the Step 3A slice as the single source of truth.
4. If the policy changes, update the shared data-access layer and this document together.
