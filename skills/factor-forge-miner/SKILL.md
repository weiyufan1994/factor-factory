---
name: factor-forge-miner
description: Use when the user wants industrial factor mining, candidate generation, template/operator sweeps, cheap screening, or a research queue before formal Factor Forge Step1-6 research.
---

# Factor Forge Miner

## Role

Factor Forge Miner is the candidate-factory layer before formal Factor Forge
research.

It does not replace `factor-forge-ultimate`. Miner creates, mutates, filters,
and queues candidate signals. Ultimate performs deep Step1-6 research,
research-quality validation, formal Step4/5/6 evidence, and promotion or
rejection.

The default mental model is:

```text
data products
-> template library
-> candidate generator
-> cheap screen
-> mechanism tagging
-> research queue
-> formal Factor Forge Ultimate
```

Miner must never present a cheap-screen result as an official factor proof.

## When To Use

Use this skill when the user asks to:

- find new factors from minute, daily, or derived state data;
- turn broad factor ideas into many candidate formulas;
- build a private-fund-style factor mining process;
- run template, operator, parameter, or formula-family sweeps;
- triage many candidates before expensive Step3/Step4/Step6 research;
- decide what data preprocessing, datamarts, template functions, or operators
  the data team should build for factor mining.

Do not use Miner for:

- formal promotion or official library acceptance;
- deep research-quality claims;
- Step6 Council revision acceptance;
- production research runs;
- clean-data mutation or Data API backfill execution.

Those belong to the formal Factor Forge workflow.

## Non-Negotiable Boundaries

Before creating or running mining artifacts, inspect the worktree and select an
active workspace. Candidate mining artifacts belong under:

```text
factor_research/<factor_id_or_family>/<research_id>/
```

or a dedicated mining workspace such as:

```text
factor_research/miner/<mining_campaign_id>/
```

Keep candidate specs, generated formulas, cheap-screen results, queues, and
notes inside that workspace. Do not write factor-specific files to repo-root
`scripts/`, baseline Step3 runtime, or repo-root `docs/operations/` unless the
file is a framework-level architecture or task document.

Cheap screen is exploratory evidence. It can rank candidates and decide whether
to send a candidate to formal research, but it cannot prove promotion.

Protect holdout data. The default full IS window is `2016-01-01..2025-07-11`.
Data after `2025-07-11` is OOS holdout-only and must not be used for repeated
template selection or parameter mining.

## Candidate Packet

Every generated candidate must have a durable packet. Minimum schema:

```json
{
  "candidate_id": "",
  "template_id": "",
  "family": "",
  "formula": "",
  "input_datasets": [],
  "required_datamarts": [],
  "operator_dependencies": [],
  "information_set": "",
  "economic_prior": "",
  "return_source_prior": "risk_premium|information_advantage|constraint_driven_arbitrage|market_structure_arbitrage|mixed|unknown",
  "payer_hypothesis": "",
  "math_object": "",
  "expected_metric_signature": {
    "ic_direction": "",
    "long_end_expected": "",
    "short_end_expected": "",
    "monotonicity_expected": "",
    "turnover_expected": ""
  },
  "falsification_tests": [],
  "cheap_screen_status": "not_run",
  "formal_research_status": "not_started",
  "promotion_forbidden_until_formal": true
}
```

The packet must say what information the formula preserves and what it deletes.
If that cannot be stated, the candidate is not ready for formal research.

## Template Library

Start from reusable logic families, not isolated clever formulas.

### 1. Price Path Shape

Examples:

- intraday momentum or reversal;
- open-to-close versus overnight gap;
- return skewness, kurtosis, tail imbalance;
- early-day move versus late-day reversal;
- path persistence, drawdown, rebound, barrier touch.

Typical math objects: minute return path, signed range path, hitting event,
partial-day conditional return.

### 2. Volume And Amount Distribution

Examples:

- volume-weighted price position inside daily range;
- high-location volume concentration;
- low-location absorption;
- minute range weighted by amount;
- abnormal amount at path extrema.

Typical math objects: occupation distribution, volume measure over price or
time, weighted path functional.

### 3. Liquidity And Flow Proxy

Examples:

- up-minute volume minus down-minute volume;
- pseudo active buy/sell pressure from OHLCV;
- large-flow state if Data API supplies it;
- turnover acceleration or deceleration;
- flow persistence before cutoff.

Typical math objects: signed flow proxy, order-imbalance state, liquidity
demand pressure.

### 4. Volatility, Jump, And Noise Structure

Examples:

- realized variance divided by range;
- intraday kurtosis or jump count;
- noisy path penalty;
- continuous sigma versus jump/tail decomposition;
- volatility after liquidity shock.

Typical math objects: quadratic variation, tail event count, jump proxy,
range-normalized realized variance.

### 5. Open, Close, And Auction Structure

Examples:

- overnight gap minus intraday continuation;
- opening overreaction;
- closing pressure;
- final-hour reversal;
- cutoff-state drift.

Typical math objects: segmented return path, conditional opening/closing
state, endpoint transition.

### 6. Value Occupation And Price-Axis State

Examples:

- price-axis occupation measure;
- point of control, high-volume node, low-volume node;
- distance from value area;
- support/overhang state.

Typical math objects: occupation measure, distribution support, state
transition over price bins.

### 7. Projection, Covariance, And Residual Structure

Examples:

- factor residual after market/industry/size/liquidity projection;
- covariance between flow and return;
- rolling beta instability;
- common-state crowding.

Typical math objects: projection residual, covariance state, conditional
exposure.

## Candidate Generation

Use industrial variation, but keep lineage auditable.

Allowed transformations:

- sign flip, rank, z-score, winsorize, neutralize;
- mean, sum, std, skew, kurtosis, quantile, tail ratio;
- difference, ratio, product, clipped product;
- rolling window, exponential decay, cutoff segment;
- condition/gate by liquidity, size, volatility, regime, or tradability;
- residualize against known exposures;
- replace raw path with derived datamart state when available.

Forbidden shortcuts:

- parameter mining on OOS holdout;
- changing data windows until a candidate looks good;
- treating a noisy one-window IC as mechanism validation;
- generating formulas without `template_id` and lineage;
- using raw minute full-window scans when a reusable datamart should exist;
- mixing candidate artifacts into baseline Step3 runtime.

## Cheap Screen

Cheap screen is a triage layer. It should be fast, broad, and conservative.

Minimum output per candidate:

```json
{
  "candidate_id": "",
  "screen_window": "",
  "universe": "",
  "data_source": "",
  "rank_ic_mean": null,
  "rank_ic_ir": null,
  "ic_hit_rate": null,
  "group_spread_gross": null,
  "long_end_gross": null,
  "short_end_gross": null,
  "monotonicity_score": null,
  "turnover_estimate": null,
  "coverage": null,
  "failure_reason": null,
  "decision": "discard|keep_as_feature|send_to_formal_research|needs_data|execution_research_needed"
}
```

Screening priorities:

1. IC and RankICIR stability.
2. Long-end and short-end separation.
3. Gross pre-cost return before trading-cost judgment.
4. Direction consistency across IS subsamples.
5. Liquidity/size/regime sensitivity.
6. Turnover only as tradability or execution flag, not an information veto.

If the signal only works on the short side, classify it as `keep_as_feature` or
risk/exclusion candidate unless the user's mandate explicitly supports short
alpha.

## Promotion To Formal Research

A candidate may enter formal Factor Forge only if it has:

- candidate packet;
- cheap-screen summary;
- data dependency list;
- economic prior and payer hypothesis;
- expected metric signature;
- falsification tests;
- workspace path;
- clear reason why formal research is worth the cost.

Formal research entry item:

```json
{
  "queue_item_version": "factorforge_miner_research_queue_item_v1",
  "candidate_id": "",
  "priority": "high|medium|low",
  "recommended_formal_route": "new_factor|feature_candidate|state_descriptor|execution_research",
  "formal_question": "",
  "required_datamarts": [],
  "missing_data_requests": [],
  "cheap_screen_artifacts": [],
  "overclaim_guard": "Cheap screen is exploratory and cannot support promotion."
}
```

## Data API / Data Team Contract

Miner needs the data layer to look like a factor factory, not a collection of
one-off raw files. When data support is missing, write a Data API task instead
of forcing Factor Forge to rescan raw data.

Required data products:

- stable datamart catalog with dataset id, schema version, coverage, QA verdict,
  lookahead policy, materialized root, and performance profile;
- reusable minute OHLCV state panels;
- daily basic / market cap / liquidity / tradability panels;
- intraday flow, distribution moment, value occupation, and volatility state
  datamarts where available;
- cheap-screen read panel with factor candidate, return labels, universe,
  controls, and exposure fields.

Required template functions:

- price path segmentation: open, early, midday, late, close;
- range and location operators;
- volume/amount weighted aggregation;
- signed-flow proxy construction;
- realized variance, skewness, kurtosis, jump proxy;
- rolling, decay, rank, neutralization, residualization;
- group spread, IC, RankICIR, hit rate, monotonicity, long/short endpoint.

Required operator standards:

- Parquet-first, projection-aware reads;
- partition pruning by date and instrument where possible;
- vectorized Polars/DuckDB/PyArrow/pandas implementations;
- no Python row loop in production-scale screen;
- bounded memory and resumable shard execution;
- catalog-first state reuse rather than raw-minute full-window fallback.

## Knowledge Backflow

Every mining campaign must write what was learned before starting the next
campaign:

- templates that produced candidates worth formal research;
- templates that failed and why;
- formula families that only work as short-side/risk filters;
- data fields or datamarts that would unlock higher-quality candidates;
- operator bottlenecks and required Data API work;
- anti-patterns: overfit parameter sweeps, unstable monotonicity, cost-only
  failures, leakage-prone fields, crowding regimes.

Knowledge writeback should distinguish:

```text
candidate_success_pattern
candidate_failure_pattern
feature_candidate
state_descriptor
data_request
operator_request
negative_knowledge
```

## Reporting Template

When reporting a Miner result to the user, use this structure:

```text
结论：候选挖矿 / 廉价筛选 / 研究队列，不是正式 promotion。

候选数量：
通过 cheap screen：
建议进入 Ultimate：
建议保留为 feature/state：
建议丢弃：
主要有效模板：
主要失败模板：
数据/API 缺口：
下一步：
边界：未启动 production research / worker / formal Step3B / Step4 / Step6 / clean data mutation。
```

## Common Mistakes

- Mistake: using one good IC table as proof of factor validity.
  Fix: mark it as cheap-screen evidence and send to formal research.

- Mistake: rejecting high-turnover candidates as no-information.
  Fix: first classify pre-cost information; then decide tradability or
  execution research.

- Mistake: building every candidate from raw minute bars.
  Fix: check datamart catalog first and request reusable state products.

- Mistake: letting template sweeps become untracked formula spam.
  Fix: every candidate needs a packet, lineage, decision, and queue status.

- Mistake: mixing Miner output into Ultimate artifacts.
  Fix: keep Miner in its workspace until a specific queue item is promoted to
  formal Step1-6 research.
