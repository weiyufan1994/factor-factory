# Phase O：Alpha018-022 机制数学与 Agentic Council 闭环修复任务说明书

Date: 2026-05-18
Source feedback: `docs/operations/factorforge-skill-feedback-alpha018-022-mechanism-agentic-council.zh-CN.md`

## 背景

Alpha018-022 生产研究暴露两个问题：

1. `economic_hypothesis -> math_hypothesis -> mechanism_math_summary` 目前能满足 schema，但不一定满足研究质量。Alpha019 被错误泛化为 price-volume microstructure，就是典型失败。
2. `--council-mode auto` 在正式研究中会降级到 deterministic scaffold。它不是 true agentic council，也不会自动进入多轮 revision loop。

这两个问题会导致 Factor Forge Ultimate 表面闭环，但实际没有达到用户要求的“公式特异性经济/数学推导 + agentic council 修订闭环”。

## 目标

Phase O 要把当前系统从“字段完整”推进到“研究有效”：

- Step6 不能把泛化机制文本当作有效机制数学。
- 机制数学必须从经济假设出发选择合适的 baseline model，并允许根据具体经济机制做 model mutation，而不是把公式套进固定模板。Baseline 可以是 stochastic process、state-space / transient-impact process、DCF/FCF/PEG valuation identity、cointegration / mean-reversion、copula / rank-dependence、jump / threshold / stopping-time、Fourier/wavelet/filtering、projection/residualization、dimensional/scaling law 等。选择模型后，必须用公开推导说明谁是 profit payer、他们为什么付钱、这个机制如何在价格/收益/现金流/订单流里产生可观察收益，并把 metric evidence 反推回假设以决定公式 mutation、kill 或 continuation。
- Council `auto` 不能在正式研究中静默把 deterministic scaffold 当 agentic council。
- Loop runner 必须区分 `awaiting_agent_results`、`scaffold_only`、`agentic_completed`、`exhausted`，不能把无法 agentic 研究误报为完成闭环。

## 核心研究原则：经济假设驱动数学建模

这是 Phase O 的核心要求，优先级高于 schema 完整性。

每个正式因子必须遵循：

```text
economic hypothesis
-> profit payer / counterparty behavior or constraint
-> selected baseline mathematical model
-> model mutation specific to this factor/formula
-> derivation of expected payoff / sign / monotonicity / horizon
-> observable estimator mapping
-> metric signature and falsification
-> formula mutation / kill / continuation decision
```

不能把数学机制写成“price-volume 因子就 microstructure”、“momentum 就 stochastic process”、“fundamental 就 DCF”的固定映射。数学工具必须由经济机制和公式结构共同决定。

示例：

- 如果经济假设是 earnings/growth risk premium，baseline 可以是 DCF / FCF / PEG 或 residual income；mutation 可以加入现金流增长状态、贴现率 shock、earnings revision jump、duration exposure；推导应说明承担了什么风险，谁在风险转移中付钱。
- 如果经济假设是 information advantage，baseline 可以是 Bayesian updating、signal extraction、state-space model、cointegration、projection/residualization；mutation 可以加入 informed flow、delayed diffusion、attention constraint；推导应说明对手方为什么慢、为什么价格没有即时反映。
- 如果经济假设是 market-structure arbitrage，baseline 可以是 transient impact process、order imbalance model、liquidity demand state、threshold/stopping-time model；mutation 可以加入 inventory constraint、forced rebalancing、crowding unwind；推导应说明 liquidity demander / panic seller / rebalancer 如何成为 payer。
- 如果公式含 rank/correlation/copula-like transforms，baseline 可以是 rank-dependence / copula / monotone transform model，但必须解释该 dependence 对应哪个经济状态，而不是只说“rank dependence”。
- 如果公式含 sign/where/threshold，baseline 应讨论 discontinuity、state transition、turnover、bucket instability 和 execution horizon。

推导可以使用积分、微分、条件期望、状态转移、随机过程、现金流折现、投影、协整、傅里叶/小波、量纲/标度等工具，但必须服务于一个明确问题：

```text
Who pays me, why do they pay, and how does the formula estimate the state that makes them pay?
```

如果 Step4/5 metrics 不支持该推导，Step6/Council 必须明确反推：

- 是 baseline model 错了；
- 是 formula estimator 错了；
- 是 sign / horizon / normalization / threshold 错了；
- 是 payer 不存在或已被成本吃掉；
- 还是只适合短腿/diagnostic，不适合 long-only promotion。

然后给出 formula mutation、additional test、或 kill criteria。

## 严格边界

允许修改：

- `factor_factory/mechanism_math/`
- `skills/factor-forge-step1/` 与 `skills/factor-forge-step2/` 中 hypothesis preservation/validation 相关脚本
- `skills/factor-forge-step6/scripts/run_step6.py`
- `skills/factor-forge-step6/scripts/validate_step6.py`
- `skills/factor-forge-step6/scripts/build_revision_council_packet.py`
- `skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py`
- `skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py`
- `scripts/run_factorforge_ultimate.py`
- `scripts/run_factorforge_ultimate_loop.py`
- smoke / acceptance scripts
- Step6 / Ultimate skill docs and contracts

禁止修改：

- Step3B formula execution semantics
- Step4 label timing
- clean data processing
- official promotion gate
- search worker behavior
- performance experimental kernel 默认路径

## P0：禁止正式研究把 scaffold 当 agentic council

### 问题

当前 `scripts/run_factorforge_ultimate.py --council-mode auto` 在需要 council 时设置：

```text
effective_mode = scaffold
```

这会让正式研究得到 deterministic scaffold，而不是 agentic council。它可以用于 smoke/fallback，但不能冒充正式 Council。

### 要求

新增正式研究 Council policy：

```text
if council_mode == auto and revision needed:
    if auto_agentic_policy == dispatch_manifest:
        build packet/taskbook/dispatch manifest
        status = awaiting_agent_results
        do not merge/attach scaffold
    elif auto_agentic_policy == scaffold_allowed_for_smoke:
        scaffold only, status = scaffold_only
    else:
        BLOCK or awaiting_agent_results, but never agentic_completed
```

建议新增 wrapper 参数：

```bash
--auto-council-policy scaffold|dispatch_manifest|block_without_agentic
```

默认：正式 production path 应为 `dispatch_manifest` 或 `block_without_agentic`，不能默认为 scaffold。为了兼容旧 smoke，可在 smoke 中显式传 `--auto-council-policy scaffold`。

### 必须输出的状态字段

`ultimate_run_report.revision_council` 必须明确：

```json
{
  "requested_mode": "auto",
  "effective_mode": "agentic_dispatch_manifest | scaffold | none",
  "formal_council_status": "awaiting_agent_results | scaffold_only | agentic_completed | not_triggered | blocked",
  "deterministic_scaffold_used": false,
  "deterministic_scaffold_formal": false,
  "agentic_required_for_formal_research": true
}
```

### BLOCK / stop tokens

建议：

```text
BLOCK_REVISION_COUNCIL_AGENTIC_REQUIRED
BLOCK_REVISION_COUNCIL_SCAFFOLD_NOT_FORMAL
```

如果选择 dispatch path，不 BLOCK，但 final outcome 必须是 `awaiting_agent_results`。

## P0：机制文本与公式字段/算子一致性校验

### 问题

Alpha019 没有 `volume`，但 Step6 机制文本出现 price-volume dependence / liquidity shock / covariance/correlation 等泛化描述。这是 research-invalid。

### 要求

新增 formula-field consistency validator。

输入来源：

- `factor_spec_master.formula_ir` 或 canonical formula expression
- Step2 `mechanism_math_contract`
- Step6 `research_iteration_master.research_judgment.research_memo.mechanism_analysis`
- loop research brief
- Council packet / derivation appendix

第一版规则不需要理解所有金融机制，但必须检查显性字段/算子冲突：

- formula 没有 `volume`，机制文本不得声称 price-volume dependence / volume liquidity / volume covariance，除非有结构化 justification。
- formula 没有 `high/low`，机制文本不得声称 high-low range / intraday range estimator，除非 justification。
- formula 使用 `sign`，机制推导必须讨论 discontinuity / threshold / turnover implications。
- formula 使用长窗口 `sum(returns,250)`，机制推导必须讨论 slow state / trend / winner state / long horizon information set。
- formula 使用 `delta(close,7)` 或 `delay(close,7)`，机制推导必须讨论 short-horizon reversal/dislocation/temporary state。
- formula 使用 raw additive terms with mixed dimensions，机制推导必须讨论 normalization/dimensional consistency，或 BLOCK/WARN。

建议 token：

```text
BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION
BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION
BLOCK_MECHANISM_FORMULA_SPECIFIC_DERIVATION_MISSING
```

## P1：公式特异性 public derivation record

### 目标

Step6 必须在 Council 前产出公开、可沉淀知识库的公式特异性推导，不要求 hidden chain-of-thought。

新增或强化：

```json
"formula_specific_derivation": {
  "version": "factorforge_formula_specific_derivation_v1",
  "economic_to_math_model_selection": {
    "baseline_model_family": "stochastic_process | valuation_identity | state_space | transient_impact | cointegration | copula_rank_dependence | jump_threshold | projection_residualization | fourier_wavelet | dimensional_scaling | other",
    "why_selected_from_economic_hypothesis": "...",
    "why_not_generic_template": "...",
    "model_mutations_for_this_formula": []
  },
  "profit_payer_derivation": {
    "payer_or_counterparty": "...",
    "why_they_pay": "...",
    "mechanism_generating_profit": "...",
    "expected_payoff_expression_or_argument": "..."
  },
  "formula_components": [],
  "latent_state_mapping": [],
  "selected_model_family": "...",
  "why_this_model_not_generic_template": "...",
  "random_object": "...",
  "latent_state": "...",
  "process_or_distribution": "...",
  "target_functional": "...",
  "formula_as_estimator": "...",
  "expected_metric_signature": "...",
  "observed_metric_comparison": "...",
  "metric_feedback_to_model": "...",
  "falsification_tests": [],
  "kill_criteria": [],
  "revision_implication": "..."
}
```

### Alpha019 regression expectation

Alpha019 必须识别：

- `rank(sum(returns,250))` 是 slow winner/trend state。
- `-sign(close_t - close_{t-7})` 是 short-horizon reversal/dislocation state。
- `minus(close, delay(close,7))` 和 `delta(close,7)` 接近重复。
- `sign` 是 discontinuous threshold transform，会提高 turnover 或造成 bucket instability。
- 机制方向是 winner pullback / temporary liquidity shock / behavioral reversal，而不是 price-volume dependence。

如果推导里出现 generic price-volume dependence，而公式无 volume，必须 FAIL。

## P1：Council packet 必须包含 formula-specific derivation

`build_revision_council_packet.py` 必须把公式特异性推导放进 packet：

```json
"formula_specific_derivation": {...},
"mechanism_formula_consistency": {...}
```

`build_agentic_council_taskbook.py` 必须要求每个 agent 在此基础上提出 revision，不允许忽略公式组件。

Agent taskbook required outputs 增加：

- model selection critique: whether the baseline mathematical model follows from the economic hypothesis;
- profit payer derivation: who pays, why, and through what price/cash-flow/order-flow process;
- model mutation proposal: how to mutate the baseline model when metrics contradict assumptions;
- critique of formula-specific derivation
- proposed alternative latent-state mapping
- expected metric signature
- falsification test
- kill criteria

## P2：Agentic Council / Loop 完整闭环

### 目标

当正式研究 `decision=iterate` 且 evidence 没有 blocked：

1. build packet
2. build agentic taskbook
3. dispatch role-specific tasks
4. 如果 runtime 无法 inline 完成，停在 `awaiting_agent_results`
5. agent results valid 后 merge
6. 只有 valid derivation-backed proposal 能进入 final revision strategy
7. Step3B child handoff 必须通过 approval/validator
8. loop runner 继续 child report

### Codex / OpenClaw runtime policy

- Codex runtime 可由主 agent spawn subagents，但当前 wrapper 未直接接 Codex agent API；在 wrapper 内应先走 `dispatch_manifest` / `manual_file`，不要假装 inline real-agent。
- OpenClaw runtime 默认由 main model/provider 派生 subagents，除非用户明确指定 provider；如果 adapter 未实现，应 `awaiting_agent_results`，不是 scaffold completed。

## Acceptance Tests

### A. Alpha019 mechanism regression

新增 smoke 或 real-case validator fixture：

```text
report_id = ALPHA019_MECHANISM_REGRESSION
formula has close/returns/sign/sum/delta/delay, no volume
mechanism text claims price-volume dependence -> BLOCK
valid derivation identifies 250-day trend + 7-day reversal + sign discontinuity -> PASS
```

必须检查：

- no volume -> no price-volume mechanism unless justified
- sign operator discussed
- long window trend state discussed
- short-horizon reversal state discussed
- formula-specific derivation exists
- derivation selects a baseline mathematical model from the economic hypothesis, not from a fixed formula-family template
- derivation explicitly states the profit payer and how their behavior/constraint generates expected payoff
- metrics contradiction feeds back into model/formula mutation or kill criteria

### A2. Economic-to-math model selection regression

Create synthetic fixtures covering at least three economic hypotheses:

```text
risk_premium / earnings or growth -> valuation / cash-flow style model allowed
information_advantage / delayed diffusion -> signal extraction / state-space / projection model allowed
market_structure_arbitrage / liquidity demand -> transient-impact / order-imbalance model allowed
```

Expected:

- validator PASS only when model selection is justified from the economic hypothesis;
- validator BLOCK when `process_or_distribution` merely restates the formula;
- validator BLOCK when every case receives the same generic model family;
- validator PASS when metrics feedback proposes coherent formula mutation or kill criteria.

### B. Auto council no silent scaffold

Run synthetic wrapper:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id <SMOKE_ITERATE_CASE> \
  --start-step 5 \
  --end-step 6 \
  --council-mode auto
```

Expected production default:

```text
revision needed
formal_council_status = awaiting_agent_results OR blocked_agentic_required
not scaffold_only completed
selection_source != deterministic_scaffold as formal result
```

A separate scaffold smoke may pass only when explicitly configured:

```bash
--council-mode scaffold
# or --auto-council-policy scaffold for smoke only
```

### C. Loop awaiting agent results

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <SMOKE_LOOP_CASE> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

Expected if no inline agentic results:

```text
final_outcome = awaiting_agent_results
stop_reason = revision_council_awaiting_agent_results
agentic_taskbook exists
no child generated_code
no clean data mutation
no official promotion
```

### D. Dispatch manifest path

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_TEST \
  --start-step 2 \
  --max-loops 10 \
  --council-mode agentic \
  --agentic-council-executor dispatch_manifest \
  --agentic-dispatch-adapter manual_file
```

Expected:

- packet exists
- taskbook exists
- dispatch manifest exists
- manual assignments exist
- final outcome `awaiting_agent_results`
- no deterministic scaffold merged as formal Council
- no generated_code mutation
- no clean data mutation
- no official promotion

## Regression Requirements

After implementation, coder must run:

- `py_compile`: PASS
- Step12 smoke: ACCEPT
- Step6 intelligence acceptance: `STEP6_INTELLIGENCE_ACCEPTED`
- Council / agentic dispatch smoke: ACCEPT or updated expected acceptance
- Phase M loop smoke: ACCEPT or updated expected acceptance
- installed skill diff clean for Step1/Step2/Step6/Ultimate if changed
- canonical pollution false

## Coder Confirmation Required

Coder final response must explicitly state:

- Did not run real factor benchmark unless requested.
- Did not process clean data.
- Did not execute search worker.
- Did not write official promotion.
- Did not change Step3B formula semantics.
- Did not make deterministic scaffold count as formal agentic Council.
- Alpha019 generic price-volume mechanism regression is covered.

## Reviewer Checklist

Reviewer should check:

1. `--council-mode auto` no longer silently formalizes scaffold.
2. Scaffold mode remains available only explicitly or for smoke.
3. Alpha019 no-volume formula cannot pass with price-volume dependence mechanism.
4. Formula-specific derivation is public and structured, not hidden CoT.
5. Council packet/taskbook include formula-specific derivation.
6. Awaiting-agent-results stop is explicit and not labeled exhausted.
7. No Step6/Council path writes generated code, clean data, official promotion, or Step3B handoff without approval.
