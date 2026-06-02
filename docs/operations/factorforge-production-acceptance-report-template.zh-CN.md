# Factor Forge Production Acceptance Report Template

## Required Acceptance Summary

Every production acceptance report must separate synthetic smoke proof from real
Mac/EC2 research proof and include:

- repo SHA and artifact root
- wrapper validation status
- Step3B sample-only status and sample metadata path
- Step4 formal factor-values owner/path
- reuse gate decision and reason
- backend status split:
  - `self_quant_evidence_status`
  - `qlib_native_status`
  - `research_decision`
- side-effect status:
  - clean data changed
  - generated code changed
  - official record written
  - search worker started
- long-side financial metrics:
  - annual return
  - Sharpe
  - turnover COGS
  - volatility drag
  - max drawdown
  - recovery days
  - drawdown recovery area

## Qlib Taxonomy

Allowed `qlib_native_status` values:

- `not_attempted`
- `preflight_blocked`
- `preflight_ready`
- `partial_payload`
- `native_minimal_success`
- `native_backtest_success`
- `failed`

`partial_payload` is not qlib success. If native full qlib success is mandatory,
anything below `native_backtest_success` must BLOCK.

## Step3B / Step4 Ownership

Step3B may only emit `step3b_sample_factor_values__<report_id>` artifacts for
executability proof. Step4 owns formal `factor_values__<report_id>` and must
byte-bind any reused cache before promotion into formal artifacts.

## Research Report Upgrade

Reports must include Dirac-style formula-implied information review:

- what the formula reveals beyond its written expression
- anomaly classification
- model-layer metric attribution
- volatility drag
- drawdown recovery area
- component-level Council revision taskbook requirements
