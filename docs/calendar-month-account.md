# Shared calendar-month account

`factor_factory.portfolio_api.backtest_calendar_month` is the public entry for
the previously accepted calendar-month close account. It is separate from the
fixed-session cohort API `backtest`. Research implements a factor class; the
framework owns the account and the Step4 adapter.

## Model and timing

Pass the complete independent exchange calendar clipped to the explicit research
window, complete true PIT membership at formation, and standard factor values.
The API accepts `datetime/instrument` plus `factor_value`, or the three long
columns `ts_code/trade_date/factor_value`. Instrument names are preserved.
Factor dates **already represent the scheduled entry session**. A certified
formation is the last session of a month followed by a supplied next-month
session. Entry is that next session. Rebalance is the next monthly entry, not a
fixed number of sessions. The final session attempts liquidation; blocked sells
remain disclosed terminal holdings. No next-valid-date substitution occurs.

The rule is the 90th type-7 percentile, inclusive of boundary ties, equal selected
weights. At least 30 finite signals, 50% coverage against the full member count
and a nonconstant signal are required. Otherwise that formation targets cash.
A missing signal month is a cash target. A missing membership denominator is an
error. Labels and controls never enter account selection.

Account quantity means **synthetic adjusted-price units**, not legal shares.
The caller binds one fixed snapshot with `price_basis_id`. Positive observed
adjusted closes mark positions. Only explicitly suspended held positions may
carry the last valid same-basis mark; missing active marks and unresolved
corporate actions/delistings block valuation. This does not establish total
return, capacity or real fills.

Raw unadjusted closes and directional raw price limits decide assumed daily
close execution. V17 suspension, ST, action and pretrade flags remain explicit.
Compatibility `buy_allowed/sell_allowed` flags do not replace final execution
checks. Sells precede buys, excess sells retry daily, new targets supersede old
ones, and blocked buys expire with their budget retained in cash. No budget is
redistributed to other buyers. Fees apply only to filled notional.

The base 30bp and stress 60bp accounts each use their own fee-aware quantities.
The gross shadow uses the base account's identical quantities and refunds fees
to idle cash; it is not an independent zero-fee account. Daily NAV includes
cash-only sessions. Recovery time is right-censored when the prior peak is not
regained by the window end. Annualization uses 252 exchange sessions.

## Python API

```python
from factor_factory.portfolio_api import backtest_calendar_month

result = backtest_calendar_month(
    factor_values,
    calendar=exchange_sessions,
    membership=formation_true_member_rows,  # ts_code, trade_date at formation
    market=account_market,
    price_basis_id=fixed_snapshot_id,
    group_boundary="lower",  # exact cut equality belongs to the lower group
)
```

`market` is a keyed daily frame with `price` (adjusted valuation mark),
`execution_close_raw`, `execution_price_basis="unadjusted_close"`, and the
explicit V17 constraint columns listed below. It can instead be the shared
`calendar_account_io.MonthlyMarket` provider, which keeps one calendar month of
projected prepared inputs in memory. No downloads, provider selection or new
data publication happen here. The default retains daily holdings for small
offline use; Step4 streams trades/stale marks and keeps only scalar daily NAV.

Result includes independent `accounts`, monthly `coverage`, `windows`,
`monthly_ic`, `monthly_labels`, and `ic_summary`. Labels are observed adjusted
close at next monthly entry divided by entry close minus one. Missing endpoints
and immature last labels stay missing. The first or next available price never
substitutes. Raw Pearson and average-tie Rank IC use paired observations.
Five-group diagnostics rank finite formation signals before labels, using
`(average_rank-.5)/N` and cuts .2/.4/.6/.8. `group_boundary="lower"` (default)
puts equality in the lower group; `"upper"` explicitly selects the alternative.
Ties remain intact in either case. This parameter affects only the five-group
label diagnostic, not IC, the upper-decile account, or factor values.
Each group reports selected and observed-label counts. Empty groups and missing
labels are unavailable, and top-minus-bottom is a label diagnostic.

`*_hac3` preserves scheduled missing month slots using the inherited Bartlett
lag-3 intercept sandwich: missing centered score contributions are zero, the
mean uses observed months, and the variance divides by observed count squared.
No dates are compressed and no missing IC is filled with zero. Degenerate
standard error remains unavailable. Partial Rank IC and Fama–MacBeth are
separate explicit calls to `research_api.evaluate_factor`; this account adapter
does not infer controls or claim they have run.

## Existing Step4 custom backend

Use the native Ultimate/Step4 custom backend plan. The adapter receives the
actual Step4-produced factor file through the existing `factor_values_source`:

```json
{
  "primary_backend": "calendar_month_account",
  "primary_evaluator_version": "factorforge_primary_evaluator_plan_v1",
  "frequency": "monthly",
  "scope": "local_is_only",
  "metric_policy": "primary_backend_explicit",
  "backends": [{
    "name": "calendar_month_account",
    "mode": "custom",
    "script_path": "skills/factor-forge-step4/scripts/calendar_month_adapter.py",
    "factor_values_source": "step4_output",
    "args": ["--prepared-inputs", "/absolute/current-study/prepared_inputs/evaluation_inputs.json"]
  }]
}
```

For an older pinned launcher, use the reviewed maintenance package's absolute
`script_path`. Do not change the study pin silently. The result records the
adapter's actual source commit, source file hashes, factor file hash, runtime
manifest hash and prepared-input hash. A source version is not itself proof of
review or research acceptance. Formal research still enters through Ultimate.

The existing prepared-input envelope remains `files[role] = {path, sha256,
columns}` with canonical-to-source column maps and absolute paths. Required
top-level fields are the current `report_id`, `scope="local_is_only"`, explicit
`is_start`, `is_end`, `price_basis_id`, `membership_semantics`, and an explicit
`group_boundary` (`"lower"` or `"upper"`) matching the frozen research specification.

| Role | Canonical columns |
| --- | --- |
| `calendar` | `trade_date` |
| `membership` | `trade_date`, `ts_code`, optionally `is_member` |
| `daily` | `trade_date`, `ts_code`, `close_adj` |
| `execution_prices` | `trade_date`, `ts_code`, `execution_close_raw` |
| `constraints` | `trade_date`, `ts_code`, `constraint_complete`, `st_state`, `suspension_state`, `up_limit`, `down_limit`, `buy_execution_action`, `sell_execution_action`, `pretrade_buy_blocked`, `pretrade_sell_blocked` |

For an explicit membership flag use
`membership_semantics="explicit_pit_true_membership_flag"` and map `is_member`
to that source column; null/unknown flags reject. Already filtered true rows use
`explicit_pit_true_rows`. Additional prepared roles are unused by this account.
Optional positive risk evidence (`listing_status`, `corporate_action_unresolved`,
`delisting_risk`, row `price_basis_id`) is retained by the market reader.
The caller remains responsible for governed data provenance, PIT membership and
snapshot correspondence; passing column names does not establish those facts.

Output uses the native evaluation payload and its sibling artifact folder.
Required `daily_nav`, `trades`, `monthly_ic`, `performance` and `coverage`
references point to actual files. Existing output is never overwritten. Failed
attempts preserve their stage, completed accounts and partial ledgers. Missing
metrics stay unavailable and cannot pass the primary completeness gate merely
because the adapter exits successfully.

## Extraction provenance and engineering checks

Source: the accepted `AMIHUD_LIQUIDITY_MECHANISM_V2` RS60 account implementation
(2026-10-01). Historical location is provenance only; runtime and tests do not
import files from that research workspace.

| Source file | SHA-256 | Shared extraction |
| --- | --- | --- |
| `rs60_eval_account_v1.py` | `b66ca8bbcc71835331daec6b7e834174408625cb406f17d619a1abe1865a7e0f` | `calendar_account.py`, byte-identical |
| `rs60_evaluator_v1.py` | `762636c364306bbcfb992bfdaf4dc52bc22203bc17b3beda87596d7d424bd5fa` | Calendar/selection mathematics, unchanged `hac_mean` |
| `rs60_evaluator_driver_v1.py` | `4dcf7c2df47335634e45fc0425d8a32d1a5c09695655964692e4fb6505d103a0` | Unchanged `performance` for initial cash 1 |
| `rs60_eval_bounded_v1.py` | `096fdfddd327e8306b0843e41df3c282f24609852d1c7813d921a3794ec1a494` | `WindowReader` generalized window/roles; unchanged `MonthlyMarket` |

The public wrapper removes historical IS dates and factor identity, validates
canonical keys, retains every scheduled formation and exposes standard results.
Prepared IO uses selected columns, predicate filters, small Arrow batches and
one-month caching. Stateful account sessions remain ordered; the independent
fee accounts are intentionally sequential to bound memory.

`tests/reference/calendar_account_v1` contains the frozen pure reference source
and selected helpers. Tests compare daily cash, holdings, fills, fees, NAV,
stale marks and terminal states, and use independent hand cash/fee and HAC
examples. A real subprocess exercises the existing Step4 custom-backend
envelope and primary result contract using synthetic prepared Parquet inputs.
These are engineering checks, not new market trials or alpha evidence.
