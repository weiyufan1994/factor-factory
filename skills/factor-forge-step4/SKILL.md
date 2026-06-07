---
name: factor-forge-step4
description: Step 4 of the Factor Forge pipeline — factor implementation, execution, and diagnostics. Consumes data_prep_master and factor_spec_master, runs the factor construction, writes factor_run_master plus execution diagnostics, and prepares evaluation handoff for Step 5.
---

# Factor Forge Step 4 Skill

## What This Skill Does

Step 4 is the **execution + evaluation orchestration layer**.
It keeps the existing execution shell (input validation, run-status discipline, artifact writeback), but upgrades the old single-path runner into a backend-driven evaluation framework.

Concretely, Step 4 now does three things:
1. consumes the Step3 Data API contract, fetches full formal input data through `factorforge_data_api`, and executes the implementation code to write formal `factor_values`
2. dispatches one or more evaluation backends
3. writes a unified run envelope plus backend-specific result payloads

Current intended backend structure:
- `self_quant_analyzer` for lightweight / quick factor checks
- `qlib_backtest` for more standard portfolio / backtest workflows
- future custom evaluators without forcing a fixed metric schema

Current practical backend maturity:
- `self_quant_analyzer` quick mode is production-usable on the current EC2 resource envelope
- `qlib_backtest` now has both a sample-stub layer and a native minimal backtest path; native execution depends on qlib-friendly signal formatting, especially `instrument` / `datetime` semantics
- Qlib native requires the Microsoft Qlib package and a provider/store. A Python package named `qlib` is not sufficient; preflight must verify `qlib.init` plus `qlib.data.D`, and must skip native execution if a non-Microsoft `qlib` package is imported.
- Standard Step4 evidence is mandatory. Agents must not fill missing Step4 evidence with ad hoc plotting scripts or one-off notebooks.

## Research Discipline

Step 4 produces evidence; it does not declare victory.

Every serious Step4 run should separate:
- signal evidence: IC, rank IC, grouped spread, decile monotonicity,
- portfolio evidence: NAV/account, turnover, cost sensitivity, drawdown, benchmark relation,
- robustness evidence: window, year, regime, universe, and liquidity buckets,
- evidence gaps: positive IC but weak portfolio, backend success but missing payload, good spread driven only by short side.

These distinctions must be visible enough for Step5/6 to judge whether the metrics support the return source or only the current implementation.

## Inputs

- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step4__{report_id}.json`

`data_prep_master` or `handoff_to_step4` must expose
`step4_data_contract.version=factorforge_step4_data_contract_v1` when legacy
local input snapshots are absent. Step4 may materialize its own run-scoped input
cache from that contract, but it must not discover raw S3/local paths or build
clean data layers itself.

## Outputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/validation/factor_run_diagnostics__{report_id}.json`
- optional factor values / parquet / csv under:
  - `factorforge/runs/{report_id}/`
- optional backend-specific evaluation artifacts under:
  - `factorforge/evaluations/{report_id}/{backend}/`
- `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`

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

Formal factor compute and evaluation must be memory-bounded. For minute bars,
tick data, large daily universes, or future model-training/evaluator paths,
Step4 must estimate peak memory before execution. If the estimate exceeds about
50-60% available RAM, or if a run shows `Killed`, exit 137, OOM-kill logs,
allocator failure, or swap exhaustion, Step4 must not retry the same
all-in-memory path. It must switch to
`batch_execution_plan.version=factorforge_batch_execution_plan_v1` or BLOCK
with `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`.

The batch plan must state memory budget, estimated peak memory, partition key,
selected columns, predicate pushdown, rolling/lookback overlap or carried state,
checkpoint/resume paths, output cache identity, and a bounded parity sample.
Step4 writes per-batch Parquet/cache outputs and releases intermediates between
batches. It must not accumulate all partitions in a Python list for final concat
unless the resulting materialization is proven within budget. Cross-sectional
rank/quantile evaluation must preserve complete per-date cross-sections or use
a documented two-pass plan. Backtest labels, masks, calendars, cost tables, and
static joins should come from reusable `backtest_base_dataset` artifacts instead
of being rebuilt for every factor, child, or sibling branch when identity and
data-window lineage match.

Full-window minute production must not fall back to generic raw-minute
streaming. For formal 2016-2026-style windows, Step4 must first consume a
declared `minute_derived_state_requirements[]` contract, currently including
`minute_derived_flow_state_v1` for signed-flow / pressure / concentration /
intraday-noise factors. The derived datamart is partitioned by `trade_date` and
must carry source data version, cutoff time, schema version, producer version,
and artifact hash. Step4 may load the derived parquet and then run only the
factor expression and evaluation. If the required derived state is absent,
incomplete, or identity-mismatched, Step4 must BLOCK with one of:
`BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED`,
`BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN`,
`BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE`, or
`BLOCK_MINUTE_DERIVED_STATE_IDENTITY_MISMATCH`. Building or refreshing the
derived state is an explicit backfill task
(`scripts/build_minute_derived_datamart.py`), not an implicit side effect of
Step4.

Default research-window policy for current minute-factor research is
in-sample through `2025-07-11`; later data is OOS holdout. Step4 should preserve
`research_window_contract` in run metadata, and Step5/Step6 must not repeatedly
fit revisions on OOS evidence.

## factor_run_master schema

```json
{
  "report_id": "string",
  "factor_id": "string",
  "run_status": "success|partial|failed",
  "implementation_path": "string",
  "output_paths": ["string"],
  "sample_window": {"start": "string", "end": "string"},
  "runtime_notes": ["string"],
  "diagnostic_summary": {
    "row_count": 0,
    "date_count": 0,
    "ticker_count": 0
  },
  "evaluation_plan": {
    "backends": [{"name": "string", "mode": "string"}],
    "metric_policy": "extensible"
  },
  "evaluation_results": {
    "backend_runs": [
      {
        "backend": "string",
        "status": "success|partial|failed|skipped",
        "summary": {},
        "artifact_paths": ["string"],
        "payload_path": "string|null"
      }
    ]
  },
  "failure_reason": "string|null"
}
```

## Core rules

1. Step 4 must produce a real on-disk run artifact or fail explicitly.
2. If execution fails, write `run_status=failed` plus exact failure reason.
3. If only part of the window runs, mark `partial`.
4. Diagnostics are mandatory even on failure.
5. Evaluation backend selection must be explicit or defaulted in a visible way; it must not be silently hard-coded into a single metrics regime.
6. Step 4 must allow multiple evaluation backends over time (`self_quant_analyzer`, `qlib_backtest`, future custom evaluators).
7. Metric schemas must remain extensible: Step 4 standardizes the envelope, not a frozen universal metric list.
8. No polished prose counts as completion.
9. If execution depends on user-selectable run parameters not already frozen in handoff/artifacts — e.g. benchmark, account size, topk, n_drop, deal price, cost model, universe, sample vs wider window, or whether to run quick-only vs deeper/native backtest — the skill must ask and confirm before launching the run.
10. qlib-native evaluators must treat signal formatting as a first-class contract item; if `instrument` / `datetime` naming or market-code normalization is unresolved, the run should be marked blocked rather than silently coercing inconsistent semantics.
10a. qlib-native evaluators must consume an explicit provider URI when available. Prefer `QLIB_PROVIDER_URI` or backend `provider_uri`, then fall back to `/home/ubuntu/.qlib/qlib_data/cn_data`, `~/.qlib/qlib_data/cn_data`, and finally `runs/<report_id>/qlib_provider`. The provider publisher is `scripts/publish_qlib_daily_provider.py`; it only converts already-clean daily data into a Qlib provider and must not clean raw data or compute factor values.
10b. If the default Step4 Python cannot import Microsoft Qlib, set `FACTORFORGE_QLIB_PYTHON` or backend `qlib_python` to a dedicated qlib-native interpreter. Step4 preflight must verify that interpreter with `qlib.init` and `qlib.data.D`, then run the qlib backend with the same interpreter.
11. Manual/temporary plotting is forbidden for official evidence. If a plot/table is needed, add it to the Step4 backend contract and rerun Step4.
12. Decile NAV and long-short NAV must be computed from daily group returns/spreads and normalized to start at `1.0`; subtracting NAV levels is invalid.

## Execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 4 --end-step 4
```

Direct `run_step4.py` / `validate_step4.py` commands are debug-only and are blocked by default for formal writes. Official agent-led runs must use `scripts/run_factorforge_ultimate.py` and produce an `ultimate_run_report__<report_id>.json` proof.

Legacy/sample Step4 entry points that look formal, including `scripts/run_step4_sample.py`, must hard block before writing canonical `objects/`, `runs/`, `generated_code/`, `evaluations/`, or `archive/` artifacts. Do not add environment bypasses to these sample blockers.

## Repository alignment note

Current repository reproducibility docs for Step 4 live at:
- `docs/contracts/step4-contract.md`
- `docs/reproducibility/step4-gap-card.md`
- `scripts/run_step4_sample.sh` (blocked from canonical writes; use the ultimate wrapper for formal execution)

Treat those files as the authoritative current repo-level reproducibility notes when deciding whether Step 4 is merely skill-visible or Bernard/Mac reproducible-level.

## Acceptance

- `factor_run_master` exists
- `run_status` is one of `success|partial|failed`
- output paths exist when run_status is success/partial
- diagnostics file exists
- handoff_to_step5 exists
- `evaluation_plan` is explicit in the run envelope
- `evaluation_results.backend_runs` exists even if some backends are skipped
- backend-specific payload paths are real when a backend claims success/partial
- `self_quant_analyzer.standard_metric_contract` exists and has no blocking checks
- all mandatory `self_quant_analyzer` tables/plots exist
- no placeholders remain
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Correctness Over Completion

Step4 must evaluate the implemented factor identity, not merely produce a status. All-skipped backend evidence, missing self-quant long-only evidence, identity mismatch, or malformed factor values must BLOCK rather than feed Step5/6.

## Long-Term Production Contract Discipline

Step4 starts production acceptance reports from `acceptance_summary`. Do not
infer `run_id` or `artifact_root` from nested `artifact_identity` when
`acceptance_summary` exists. The summary must split wrapper status, backend
status, reuse gate status, side effects, and research metrics.

Report qlib as `qlib_native_status=<taxonomy>`. Never call qlib success unless
status is `native_backtest_success` or explicitly `native_minimal_success` for a
minimal-only run. The phrase "qlib partial success" is banned.

Step4 consumes `standard_formula_fields_contract` and `derived_field_contract`
from Step2/Step3A; it must enforce unit policy, lookback policy, leakage policy,
and source fields before formal compute. Do not write "derive if needed" without
source fields. Do not describe Step3B formal factor values; formal factor values
are Step4-owned.

Prompt vocabulary required for downstream continuity: `evidence_status`,
`formula_implied_information`, `metric_anomaly_review`,
`model_linked_metric_signature`, `volatility_drag`,
`drawdown_recovery_area`, `component_ablation`, and
`direction_losing_transform_review`.

Explicit bans: no "partial run without layer"; no raw formula restatement as
mechanism; no generic stochastic process as explanation.

Required literal bans for validator coverage: derive if needed without source fields; raw formula restatement as mechanism.
