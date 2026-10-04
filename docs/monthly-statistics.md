# Monthly conditional and paired signal diagnostics

These explicit APIs consume existing factors, decimal forward returns and
independent monthly membership. They do not calculate factors, run accounts,
select a control model, fetch data or establish promotion authority. Research
chooses a frozen profile before observing its results.

## Opt-in C11 profile

`factor_factory.monthly_statistics.evaluate_c11_monthly` is the explicit
`c11_rank_quantile_v1` profile. It is not an implicit default for other research
or for `research_api.evaluate_factor`. Inputs use the standard factor frames:
`datetime/instrument` index or `ts_code/trade_date` long keys. Factor keys are
already scheduled monthly entry dates; they are not shifted again. Labels
contain `forward_return`. Controls contain exactly the seven raw columns below.
Infinities, duplicate keys and keys outside the declared membership reject.
NaNs remain missing. No factor, raw control or label is imputed.

At each month, first form H = complete(factor, return, all raw7). All following
ranks are computed inside this SAME H with average ties and u=(rank-.5)/N.

| Raw column | Fixed C11 terms |
| --- | --- |
| `size_raw` | size=u_size; size_square=(u_size-.5)^2 |
| `value_raw` | value=-u_value |
| `volatility_raw` | volatility=u_vol; volatility_square=(u_vol-.5)^2 |
| `activity_raw` | activity=u_activity; activity_square=(u_activity-.5)^2 |
| `low_price_raw` | low_price=u_low_price |
| `short_reversal_raw` | short_reversal=-u_short_reversal |
| `momentum_raw` | momentum=u_momentum |
| activity and volatility | interaction=(u_activity-.5)(u_vol-.5) |

Partial Rank IC calls the existing `partial_rank_ic_periods`: correlate the
residuals of average-rank factor and average-rank return after BOTH are
projected on Z=[intercept,C11]. Residuals are not re-ranked; no control is
removed and no ridge is used. At least 100 complete cases, full Z rank and
positive residual variance are required. Its existing centered, normalized SVD
uses relative tolerance float64_eps*max(N,12).

Fama–MacBeth calls the existing `fama_macbeth_periods`: regress the raw simple
return on intercept, rank-quantile factor and C11. This profile requires N>=100
and full design rank, with rcond=1e-10 inherited from the accepted C11 model.
The generic kernel's new minimum/rcond options default to its previous behavior.
Constant or collinear controls produce Unknown, rather than a reduced model.
Per-month reasons and membership/support flags are returned. Same-support raw
IC is descriptive and can be available below the partial/FMB minimum.

The supplied `calendar_slots` must contain every monthly entry slot, including
months with no factor output or controls. `expected_index` must come from the
independent calendar and PIT membership, not observed factor rows. Summary HAC3
reuses `calendar_month.hac_mean`: Bartlett lag3, original month slots retained,
observed-score sandwich with denominator n_observed squared, no finite-sample
multiplier. Missing centered scores contribute zero to the sandwich; missing
monthly statistics are not filled with zero observations. Nonpositive SE stays
Unknown. Normal-approximation 95% two-sided intervals and 99.5% one-sided lower
bounds are descriptive inference, not a research or promotion decision.

```python
from factor_factory.monthly_statistics import evaluate_c11_monthly

diagnostic = evaluate_c11_monthly(
    factor_values, current_monthly_labels, raw7_controls,
    expected_index=pit_member_keys_at_entry,
    calendar_slots=all_monthly_entry_dates,
)
```

## Consume completed Step4 output without running the account again

The shared CLI is `scripts/evaluate_monthly_diagnostics.py`. All choices are
explicit; it never selects the latest file or guesses a factor/control column.

```sh
python /reviewed/source/scripts/evaluate_monthly_diagnostics.py \
  --report-id CURRENT_REPORT \
  --manifest /current/study/objects/runtime_context/runtime_manifest.json \
  --factor-values /current/study/runs/CURRENT_REPORT/factor.parquet \
  --primary-payload /current/study/evaluations/CURRENT_REPORT/evaluation_payload.json \
  --controls-binding /explicit/raw_control_binding.json \
  --control-profile c11_rank_quantile_v1 \
  --output /current/study/evaluations/CURRENT_REPORT/c11_diagnostic.json
```

The factor file must be the runtime-selected Step4 file. The selected successful
local primary payload must bind that exact factor path/hash and the existing
account's prepared-input path/hash. The consumer uses its current monthly label
artifact and only calendar/membership roles from those original prepared inputs;
daily market and execution files are not opened. Current report identity,
price basis and research window must agree. The consumer writes a new diagnostic
and sibling support/period files without overwriting any existing result. It
does not amend the primary payload or claim Step4/5 has been rerun.

The controls binding contains `monthly_controls[YYYYMMDD formation]` entries
with absolute `path`, `sha256`, `signal_date`, `entry_date`, `label_end_date`
(null for an immature final window), `source_kind="full_member_attrition"`,
and source provenance fields. Bindings and selected rows must match the exact
calendar window. Only `ts_code`, `signal_date`, `entry_date` and raw7 are read
from each prepared Parquet. Old study identity is retained as source provenance;
old factors, gates, labels, complete-case selections and ranks are not consumed.
Extra source members are explicitly counted and restricted to CURRENT PIT
membership. Missing references retain an unavailable month; bad declared hashes
or windows fail. Governance and the frozen raw7 definitions remain the research
owner's responsibility; filenames alone do not prove PIT correctness.

The diagnostic records actual code commit/file hashes and all input hashes,
including the current labels and original account payload. Source pin changes
are not performed by this consumer. The research owner runs real-input statistics
within its approved trial scope. Engineering validation uses synthetic data.

## Paired baseline comparison

`paired_monthly_rank_ic(reference, alternative, forward_returns,
expected_index=..., calendar_slots=...)` selects common H=finite(reference,
alternative,return), requires at least 30 observations, and computes both
average-tie Rank ICs on H. Delta is IC(reference)-IC(alternative). It applies
the SAME existing HAC3 directly to Delta's original monthly slots, preserving
covariance between the pair. It does not combine independent standard errors.
It exposes 95% intervals, a 99.5% one-sided lower bound and `positive_p`; with
nonpositive SE these remain Unknown. There is no equivalence-test conclusion.
The reference/alternative order is explicit and is never inferred from a name.

## Provenance and tests

The fixed C11 transformation and FMB tolerance come from accepted
`AMIHUD_LIQUIDITY_MECHANISM_V2` `rs60_evaluator_v1.py`, SHA256
`762636c364306bbcfb992bfdaf4dc52bc22203bc17b3beda87596d7d424bd5fa`.
The frozen pure selection is in `tests/reference/calendar_account_v1/conditional.py`.
The old study is never imported at runtime or in tests. The profile does not
copy that study's factor, signal gate or support.

Offline checks include hand rank/sign/square examples, exact frozen design
parity, independent normal-equation partial IC, old FMB coefficient parity,
N=99/100 and N=29/30 boundaries, singular/zero-residual Unknown, missing month
HAC arithmetic, paired covariance, and an actual CLI invocation with synthetic
Parquet/CSV inputs and no available daily market. These are engineering evidence,
not newly observed market diagnostics.
