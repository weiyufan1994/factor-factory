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

When Step3B run metadata declares
`performance_profile.csv_output_profile.csv_output_policy`, Step4 must respect
it for factor CSV writeback. `full_csv` and legacy missing metadata may write or
refresh the full factor CSV for compatibility. `sample_csv` and `no_csv` must
not cause Step4 to generate or refresh `factor_values__{report_id}.csv`; Step4
should continue to evaluate from parquet and record the observed policy in
run metadata.

Step3B `step3b_sample_factor_values__{report_id}` artifacts are sample
executability evidence only. Step4 must not treat them as formal factor values;
if a legacy Step3B formal-looking parquet exists, Step4 must recompute from the
Data API/full input contract unless the existing metadata proves it was already
written by Step4.

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
