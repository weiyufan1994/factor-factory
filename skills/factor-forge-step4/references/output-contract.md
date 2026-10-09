# Step4 output and timing

All paths are relative to the declared factor workspace.

## Outputs

- `objects/factor_run_master/factor_run_master__{report_id}.json`
- `objects/validation/factor_run_diagnostics__{report_id}.json`
- optional factor values / parquet / csv under:
  - `runs/{report_id}/`
- optional backend-specific evaluation artifacts under:
  - `evaluations/{report_id}/{backend}/`
- `objects/handoff/handoff_to_step5__{report_id}.json`

Mandatory `self_quant_analyzer` artifacts:
- `rank_ic_timeseries.png`
- `pearson_ic_timeseries.png`
- `coverage_by_day.png`
- `quantile_returns_10groups.csv`
- `quantile_nav_10groups.csv`
- `quantile_counts_10groups.csv`
- `quantile_summary_table.csv`
- `long_short_returns_10groups.csv`
- `long_short_nav_10groups.csv`
- `quantile_nav_10groups.png`
- `quantile_counts_10groups.png`
- `long_short_nav_10groups.png`

`self_quant_analyzer/evaluation_payload.json` should include
`performance_profile.version=factorforge_self_quant_performance_profile_v1`
with merged row count, phase timings for factor/daily load, forward-return
merge, IC calculation, quantile assignment, long-side evidence, table writes,
plot writes, total runtime, rows/sec, and parallelism. This is measurement
metadata only; it must not change promotion gates or research semantics.

The same payload should include
`signal_timing_contract.version=factorforge_signal_timing_contract_v1`
documenting that close-after-market factor values at t are evaluated against
next-trading-day returns (`pct_chg.shift(-1)`), merged on `datetime` and `code`.
Same-day returns must not be used as IC or NAV labels.

For `factorforge_web_evaluation_contract_v2`, the stricter executable timing
overrides that legacy diagnostic alignment: a signal formed after close t is
entered at close t+1 and exited at close t+2. The label must be computed as
`close.shift(-2) / close.shift(-1) - 1`; `pct_chg` is not an allowed substitute.
The evaluation contract must also carry
`position_exit_policy=close_t_plus_2` and the exact
`payoff_label_expression`; Step4 blocks if either binding is missing or changed.
The shared evaluation context must use
`factorforge_shared_evaluation_context_v2` and preserve this exact policy for
every backend and Council revision metric.

Intraday signals need an explicit timing evaluator instead of being judged only
by the default daily close-after-market label. If a factor uses minute/tick data
with a cutoff such as 14:50 or 14:55, Step4 must record
`intraday_signal_timing_contract.version=factorforge_intraday_signal_timing_contract_v1`
and evaluate only label modes whose information set is legal, for example
`close_to_next_open`, `close_to_next_close`, `close_to_next_vwap_0935_1000`,
`close_to_next_vwap_0930_1030`, or `open_to_close_next_day`. The payload must
state `signal_cutoff_time`, `execution_price_policy`, `label_price_policy`,
`information_set`, and `same_day_return_used_as_label=false`. Without this
contract, Step4 may report the default daily result but must not conclude that a
14:50/14:55 trading hypothesis has been falsified.

When Step3B run metadata declares
`performance_profile.csv_output_profile.csv_output_policy`, Step4 must respect
it for factor CSV writeback. `full_csv` and legacy missing metadata may write or
refresh the full factor CSV for compatibility. `sample_csv` and `no_csv` must
not cause Step4 to generate or refresh `factor_values__{report_id}.csv`; Step4
should continue to evaluate from parquet and record the observed policy in
run metadata.

Step3B `step3b_sample_factor_values__{report_id}` artifacts are sample
executability evidence only. Step4 must not treat them as formal factor values;
Step3B must not run full formal data or produce a full compute cache. Step4 must
always compute full-data formal `factor_values__{report_id}` itself, except when
reusing a prior Step4-owned formal factor parquet whose identity/hash lineage
matches. Step3B metadata may be used for implementation audit and CSV policy,
but Step4 must not consume `step3b_sample_factor_values` as a formal compute
cache even if row/date/ticker counts appear to match.

## Stable results

Use `factor_factory.research_api` for factor statistics and
`factor_factory.portfolio_api` for the selected account model. IC/event/Fama–MacBeth
outputs remain statistical analyses. Metrics keep stable names, values, units,
sample counts and unavailable reasons. Preserve `evaluation_plan` and each
backend's `status`, actual `payload_path` and artifacts in `factor_run_master`.
A failure records diagnostics and its reason; a partial window remains partial.
The quick self-quant output is `signal_diagnostic`, not account evidence.

Decile/long-short diagnostics are formed from group returns/spreads and NAV
starts at one; subtracting NAV levels is not a return calculation. A new required
plot or table belongs to the reusable backend and rerun, not an unrecorded
per-factor replacement for missing required evidence.
