# Alpha101 Batch State Sync

Date: 2026-06-24

Scope:

`factor_research/Alpha*/` and `factor_research/alpha101_batch/alpha101_batch_qlib_20260611`

This note syncs the Alpha101 batch status after two latest knowledge deposits:

1. Alpha015 post-rerun candidate packet.
2. Alpha019 LOOP01 execution-readiness packet.

It is a coordination and knowledge artifact. It is not a Step3B/Step4/Step6
result and not promotion evidence.

## Current Batch Decision

```text
best_current_candidate: Alpha015 parent
next_executable_research: Alpha019 LOOP01
Alpha019 execution_status: pending_human_approval
do_not_run_child_without_approval: true
revision_loop_cap: <=5
revision_loops_consumed_by_next_child_if_approved: 1
```

## Alpha015 Status

Latest knowledge:

```text
docs/alpha015_candidate_packet_post_rerun_20260624.zh-CN.md
knowledge/canonical/alpha015_candidate_packet_post_rerun_20260624.json
```

Current classification:

```text
candidate_library: yes
feature_candidate: yes
official_factor_library: no
best_branch: ALPHA015_SWEEP_TURNPEN_A040_20160101
mechanism_claim_level: component_validated
stochastic_process_status: framing_only
payer_validation: not_validated
```

Formula decomposition:

$$
F^{015}_{i,t}=X_{i,t}L_{i,t}G_{i,t}
$$

where:

$$
X_{i,t}
=
-\sum_{k=1}^{7}\operatorname{rank}(C_{i,t-k+1})
$$

$$
C_{i,t}
=
\operatorname{corr}_{7}
\left(
\operatorname{rank}(H_{i,\cdot}),
\operatorname{rank}(V_{i,\cdot})
\right)_t
$$

$$
L_{i,t}=\operatorname{rank}(A_{i,t})
$$

$$
G_{i,t}=0.40+0.60\left(1-\operatorname{rank}(T_{i,t})\right)
$$

Interpretation:

- $X_{i,t}$ is a short-window price-volume pressure state.
- $L_{i,t}$ confirms that the state has enough participation.
- $G_{i,t}$ softly avoids pure high-turnover crowding.

Formal rerun metrics for parent:

| Metric | Value |
|---|---:|
| formal signal coverage | 99.2156% |
| RankIC mean | 0.060225 |
| RankIC IR | 0.541872 |
| long annual return | 22.2511% |
| long Sharpe | 0.9382 |
| max drawdown | -39.54% |
| recovery days | 704 |
| daily turnover | 24.49% |
| cost-adjusted annual return | 3.7472% |
| cost-adjusted Sharpe | 0.1579 |

Reading:

Alpha015 remains the strongest current Alpha101 candidate, but it is not clean
official-library material. It needs payer validation, stochastic validation,
investability/capacity checks, and model-combination marginal contribution.

Do not repeat:

- do not continue simple stronger turnover gates;
- do not promote LOOP01 or LOOP02 from local IC or turnover changes;
- do not call Alpha015 pure size-neutral or liquidity-neutral residual alpha.

## Alpha019 Status

Latest knowledge:

```text
docs/alpha019_loop01_execution_readiness_20260624.zh-CN.md
knowledge/canonical/alpha019_loop01_execution_readiness_20260624.json
```

Current execution state:

```text
parent_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101
proposed_child_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101__LOOP01__ALPHA019_SMOOTHED_PULLBACK_PERSISTENCE_V1
execution_status: pending_human_approval
execution_allowed_by_default: false
active_handoff_to_step3b: absent
```

Parent mechanism:

$$
S_{i,t}=B_{i,t}(1+M_{i,t})
$$

where:

$$
B_{i,t}=-\operatorname{sign}(C_{i,t}-C_{i,t-7})
$$

$$
M_{i,t}
=
\operatorname{rank}_t
\left(
1+\sum_{k=0}^{249}r_{i,t-k}
\right)
$$

Parent weakness:

$$
\operatorname{NetEdge}
=
\operatorname{GrossEdge}
-
\operatorname{Turnover}\times\operatorname{Cost}
<0
$$

Recommended child:

$$
F^{019,\mathrm{child}}_{i,t}
=
\operatorname{mean}_{5}
\left[
\operatorname{rank}_{t}
\left(
\frac{C_{i,t-7}-C_{i,t}}{C_{i,t-7}}
\right)
\right]
\left(1+M_{i,t}\right)
$$

Formula-IR:

```text
mean(rank(((delay(close, 7) - close) / delay(close, 7))), 5)
*
(1 + rank((1 + sum(returns, 250))))
```

Preflight status:

```text
parse_status: success
formula_hash: 8cb8e209277990fb9bb5af3df4c240ade2e010144e16144943bd32d3a017a3e8
required_fields: close, returns
operator_set: delay, divide, mean, minus, multiply, plus, rank, sum
max_formula_ir_lookback: 250
synthetic_non_null_factor_rows: 852
synthetic_nonnull_dates: 71
```

The preflight proves feasibility only. It does not prove alpha quality.

## Execution Gate

The next formal action is:

```text
wait_for_user_approval: approve Alpha019 LOOP01
```

After explicit approval, use the formal Factor Forge revision path:

1. materialize the child revision package;
2. produce child Step1/2/3 artifacts and executable revision spec;
3. run the single wrapper from Step3B through Step6;
4. write child evidence and failure/success knowledge before any next loop.

Forbidden:

- do not run the child from a disabled provisional handoff;
- do not mutate baseline Step3;
- do not change portfolio policy, rebalance, decile trading, or short-leg use
  to rescue the factor;
- do not skip Step6 knowledge writeback.

## Batch-Level State

```text
Alpha015: candidate / feature candidate, not official
Alpha019: next child ready for approval, not executed
Alpha040: positive information, weak standalone economics
Alpha044: information exists, cost/drawdown blocked
Alpha083: feature-state only
Alpha005/Alpha007/Alpha013/Alpha042: closed or deprioritized unless new mechanism appears
```

This state supersedes any older queue note that does not mention the Alpha015
post-rerun candidate packet or Alpha019 execution-readiness packet.
