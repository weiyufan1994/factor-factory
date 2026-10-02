# Human-reproducible Step3–5 delivery

The user must be able to inspect and rerun the code without an LLM. Deliver
working code and data slices, not just claims that tests passed. Use the shared
SDK/analysis modules; do not build a new wrapper, calendar, validator or account
engine for each factor.

## Factor implementation

New factor code is a class instance with explicit parameters and named frame
inputs. Prefer `BaseFactor`, `PriceVolumeFactor` or `FundamentalFactor` from
`factor_factory.factors` when available in the selected checkout. Export the
instance as `FACTOR`; implement `compute(inputs)`. Its shared `run()` validates
the output. Operator, direct-code and hybrid implementations have the same exit.
Legacy `compute_factor` functions remain compatibility inputs, not a reason to
force a per-factor rewrite of old pinned research.

Keep data fetching, factor calculation, forward labels, statistical analysis
and account simulation separate. A factor instance may use reusable numerical
helpers; it must not fetch evaluation labels or calculate its own performance.
Do not mutate shared input frames. Annotate the mathematical expression, units,
lookback, availability time, missing/zero conventions and material approximations
where the code implements them. Use named parameters; avoid hidden globals or
unexplained numerical constants.

The portable daily factor table is a sorted, unique `datetime/instrument`
MultiIndex and one real `float64` column `factor_value`. Preserve instrument
identity; an external provider's symbol mapping must be explicit. Existing
`ts_code/trade_date/factor_value` long tables convert at the shared boundary.
Do not guess a numeric/signal column, coerce bad strings, deduplicate by choice,
replace infinity, drop unexplained keys, or fill missing factors with zero.
Valid warmup/domain NaNs and genuine zero values are different and are retained.

## Required human handoff

- Full annotated implementation and invoked local helpers, explicit parameters,
  selected data inputs and an exact runnable command. Link actual files, not
  screenshots of partial code. Where available, `write_factor_review` supplies
  an offline HTML view with line numbers and copyable code.
- Input sample plus output `head`, `tail`, and fixed first/middle/last evaluated
  date slices. Include a relevant missing/warmup/tie/zero case when present,
  row/date/instrument counts and dtypes. State sorting and slice selection;
  never cherry-pick the best-performing dates. Export the full factor table
  separately as Parquet/CSV with its keys.
- A small, independent hand-calculated example: list inputs, expected outputs
  and tolerances before comparison. Same-implementation parity and an execution
  PASS are not independent mathematical or timing evidence.
- Step4's actual backend/analysis, settings, label horizon/entry timing, sample
  counts, metric definitions and computed values. Every metric has a stable
  name, value, unit, sample count and unavailable reason. Undefined is null,
  not zero or Infinity. Do not annualize overlapping labels into an account NAV.
- A clear split between code/interface correctness, preliminary empirical
  evidence, account-model results and the economic conclusion.

Step3 delivers a bounded sample, not full research metrics. Step4 adds complete
values and evaluation. Step5 verifies and archives the same code/table/metrics
and presents the human handoff before sending economic conclusions to Step6.
Missing handoff content means delivery is incomplete; it does not justify new
permissions, signatures or a data-production approval loop.

## Common analysis modules

Use `factor_factory.research_api` in checkouts that include it. IC, event-return
analysis and Fama–MacBeth are separate preliminary analyses over explicit
labels. Qlib and the self-account engine are account backends with explicit
configuration; unsupported dependencies must be reported as unsupported, never
replaced by group means. Backend-specific extensions may add metrics without
changing the shared core's names or units.

An old pinned checkout may not contain these new modules. Report that version
boundary instead of claiming it has been upgraded or pasting a replacement
engine into the factor. An engineering demo is not a resumed research run.
