> [中文版本](step3-contract.zh-CN.md)

# Step 3 contract

## Current judgment
Step 3 now has a first tiny committed reproducibility substrate design, but it is more demanding than Step 1/2 because current validation requires local input snapshots and Step 3B must emit first-run outputs when they exist.

## Current committed reproducibility inputs
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

## Current committed sample runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## Input class
- `factor_spec_master__{report_id}.json`
- optional `handoff_to_step3__{report_id}.json`
- Step2 research fields: `thesis`, `research_contract`, `math_discipline_review`, `learning_and_innovation`
- `alpha_idea_master__{report_id}.json`
- tiny local minute/daily sample inputs
- runnable implementation file for Step 3B first-run generation

## Output class
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- generated/editable code artifacts
- first-run factor-value outputs
- `handoff_to_step4__{report_id}.json`

## Step3B / Step4 Boundary
Step3B only proves that the implementation can produce first-run `factor_values` from the prepared local snapshot. Step3B must not run Step4 responsibilities:
- no IC report,
- no quantile NAV,
- no portfolio charts,
- no backend evaluation.

Those belong to the standard Step4 evaluator. If Step3B times out while computing quantile tables, backtest charts, or portfolio diagnostics, treat it as a workflow-boundary error rather than a factor-implementation failure.

## Date-Key Standard
Step3A / Step3B / Step4 boundaries must tolerate:
- `YYYYMMDD` strings,
- `YYYYMMDD` integers,
- `YYYY-MM-DD` strings,
- pandas Timestamp values.

Step4 consumers must normalize dates with `factor_factory.data_access.normalize_trade_date_series()` instead of letting each factor script define its own parsing convention.

## Step 2 research context carry-through
Step 3B directly consumes Step 2's factor spec and handoff. It must write a consistent
`step2_research_context` into the implementation plan, qlib expression draft, hybrid scaffold,
Step4 handoff, generated code review comments, and first-run metadata when generated. The
context must preserve at least target statistic, economic mechanism, expected failure modes,
reuse instructions, and implementation invariants so Step4/5/6 evaluate the implemented thesis
rather than an isolated numeric column.

## Reproducibility warning
Step 3 tiny reproduction currently relies on a thin wrapper that installs fixture files into the runner-expected object and local-input paths, because the existing Step 3 scripts are built around that object contract.
