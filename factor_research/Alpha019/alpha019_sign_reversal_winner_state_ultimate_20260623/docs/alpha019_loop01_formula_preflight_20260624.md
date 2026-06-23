# Alpha019 LOOP01 Formula Preflight

Date: 2026-06-24

Report:

```text
parent_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101
proposed_child_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101__LOOP01__ALPHA019_SMOOTHED_PULLBACK_PERSISTENCE_V1
status: preflight_only_pending_human_approval
```

This is not a Step3B run and not Step4 evidence. It is a read-only formula
feasibility check for the already proposed child in
`alpha019_next_branch_approval_packet_20260623.zh-CN.md`.

## Proposed Child Formula

$$
F^{019,\mathrm{child}}_{i,t}
=
\operatorname{mean}_5
\left[
\operatorname{rank}_t
\left(
\frac{C_{i,t-7}-C_{i,t}}{C_{i,t-7}}
\right)
\right]
\cdot
\left(
1+
\operatorname{rank}_t
\left(
1+\sum_{k=0}^{249}r_{i,t-k}
\right)
\right).
$$

Formula-IR draft:

```text
mean(rank(((delay(close, 7) - close) / delay(close, 7))), 5)
*
(1 + rank((1 + sum(returns, 250))))
```

## Parse And Operator Preflight

The Formula-IR parser accepts the expression.

```text
parse_status: success
formula_hash: 8cb8e209277990fb9bb5af3df4c240ade2e010144e16144943bd32d3a017a3e8
required_fields: close, returns
operator_set: delay, divide, mean, minus, multiply, plus, rank, sum
max_formula_ir_lookback: 250
```

The child formula uses the same slow 250-day lookback class as the parent.
The existing Step3A/Step3B long-lookback fixes are therefore relevant:

1. Step3A sample windows must expand enough to cover at least 250 prior return
   observations.
2. Step3B sampling must preserve enough date history for selected tickers.
3. Step4 coverage should use warmup-adjusted coverage for natural rolling
   warmup nulls.

## Synthetic Evaluation Smoke

A bounded synthetic daily panel was evaluated with the optimized Formula-IR
engine.

```text
rows: 3840
non_null_factor_rows: 852
nonnull_dates: 71
first_nonnull_date: 20201215
last_nonnull_date: 20210323
factor_value_min: 0.15555555555555553
factor_value_max: 1.672222222222223
```

This proves the expression is executable and does not collapse to all-null on a
panel with enough lookback history. It does not prove alpha quality.

## Execution Boundary

The parent Step6/Council artifacts still require human approval before code or
Step3B execution:

```text
human_approval_required: true
execution_allowed_by_default: false
active_handoff_to_step3b: absent
```

After explicit approval, the correct next action is to materialize the child
through the formal Factor Forge revision path and then run the single wrapper
from Step3B through Step6.
