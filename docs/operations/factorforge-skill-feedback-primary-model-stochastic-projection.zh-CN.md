# Factor Forge Ultimate 问题反馈：将“主机制模型 + 随机价格过程投影”纳入正式研究合同

Date: 2026-05-25

Audience: Factor Forge Architect

Authoring context:

- 用户希望 Factor Forge Ultimate 不只是解释已有公式，而是具备“从物理/数学层面理解金融市场，并通过公式推导描述市场行为、发掘新因子”的研究能力。
- 该要求适用于所有使用 Factor Forge Ultimate 的主 agent 和运行体，包括 Codex、Humphrey、Bernard，以及 Step6/Council subagents。
- 本反馈不是要求把所有因子强行解释成 stochastic process，而是要求每个因子都有一个最贴合经济假设的 primary mechanism model，并在正式落地为因子表达式前，通过 stochastic price-process projection 进行统一的价格分布一致性检验。

Related existing docs / contracts:

- `docs/operations/factorforge-math-research-discipline.zh-CN.md`
- `docs/operations/factorforge-skill-feedback-main-agent-mechanism-contract.zh-CN.md`
- `docs/operations/factorforge-skill-feedback-council-derivation-engine.zh-CN.md`
- `docs/operations/factorforge-skill-feedback-multibranch-exploration-exploit.zh-CN.md`
- `skills/factor-forge-ultimate/SKILL.md`
- `skills/factor-forge-research-brain/SKILL.md`
- `skills/factor-forge-step1/SKILL.md`
- `skills/factor-forge-step2/SKILL.md`
- `skills/factor-forge-step6/SKILL.md`

## Executive Summary

当前 Factor Forge 已经具备较多机制研究基础：

1. Step1/2 已要求 `economic_hypothesis` 与 `math_hypothesis_candidates`；
2. Step6 已有 `math_discipline_review`、主 agent mechanism memo、Council、prior revision memory、multibranch exploration/exploit；
3. Research Brain 已要求先判断 return source，再解释 metrics；
4. Alpha026/P4 等测试已经证明 Council 可以进入 derivation-oriented loop，而不是单纯 verdict engine。

但仍缺一个顶层统一原则：

```text
A factor is not a formula first.
A factor is a falsifiable market-process model.
The formula is only an observable estimator of that model.
```

中文表述：

```text
因子首先不是公式，而是一个可证伪的市场过程模型；公式只是该模型的观测器。
```

因此建议新增正式合同：

```text
Every formal factor must have:

1. a primary mechanism model selected from the economic hypothesis;
2. a stochastic price-process projection explaining how that mechanism changes future return distribution;
3. a formula-specific observable estimator mapping;
4. expected metric signature and falsification tests;
5. Step6/Council revision logic that can map failed metrics back to either:
   - economic hypothesis,
   - primary mechanism model,
   - stochastic projection,
   - observable estimator,
   - or implementation/data contract.
```

## User Requirement Restated

用户要的不是“用物理术语装饰因子解释”，也不是“每个因子都套一个空泛 SDE”。

用户真正要求的是：

```text
market behavior
-> economic hypothesis
-> choose the best math/physics model
-> derive latent state / observable estimator / target functional
-> map to executable factor expression
-> evaluate metrics
-> revise the model or estimator based on falsification
```

其中：

- `economic hypothesis` 说明因子为什么可能赚钱，以及谁付钱；
- `primary mechanism model` 说明哪个数学/物理结构最适合描述该经济机制；
- `stochastic price-process projection` 说明该机制最终如何影响未来收益分布；
- `factor expression` 是可观测数据上的状态估计器，不是研究起点；
- Step6/Council 应像推导物理或数学公式一样推导下一轮机制，而不是投票式 reject 或随机调参。

## Key Principle: Primary Model Is Free, Stochastic Projection Is Benchmark Translation

### Primary mechanism model must be selected, not templated

主模型不应固定为 stochastic process。它必须根据经济假设、对手盘、市场结构、可观测字段和公式算子选择。

可选模型族包括但不限于：

- `stochastic_process`
  - diffusion, jump process, stochastic volatility, state transition, stopping time;
- `microstructure_response_function`
  - order-flow impact, transient impact, liquidity elasticity, volume-conditioned response;
- `dimensional_scaling_analysis`
  - size/liquidity/turnover/volatility scaling, power law, invariance;
- `potential_field_or_barrier_model`
  - support/resistance, cost basis zones, price barriers, limit-up/limit-down, volume-at-price mass;
- `entropy_or_information_theory`
  - information shock, entropy production, sequence complexity, attention disorder;
- `wavelet_or_spectral_model`
  - multi-horizon energy, frequency migration, resonance, signal/noise decomposition;
- `copula_or_dependence_model`
  - tail dependence, nonlinear rank dependence, asymmetric co-movement;
- `regime_switching_model`
  - market structure, liquidity state, style regime, bull/bear transition;
- `behavioral_constraint_model`
  - retail, public funds, insurance, mandate-constrained institutions, trend followers;
- `inventory_or_execution_model`
  - dealer/inventory pressure, execution demand, rebalance flow, impact cost;
- `network_or_contagion_model`
  - theme propagation, industry spillover, crowding network, capital-flow contagion.

硬要求不是“必须选 stochastic process”，而是：

```text
The agent must justify why the selected primary model best matches the economic hypothesis and formula-specific observables.
It must also state why key alternatives are less suitable.
```

### Stochastic process should be the projection layer

虽然 primary model 不固定，但所有影响股价的机制最终都应回答同一个问题：

```text
Given information set F_t, how does the signal change the conditional distribution of r_{t+1}?
```

因此建议把 stochastic process 定位为统一的 benchmark translation layer：

```text
dP_t / P_t = mu(S_t, Z_t) dt
           + sigma(S_t, Z_t) dW_t
           + J(S_t, Z_t) dN_t
           + impact(S_t, Z_t, liquidity_t) dt
           + observation_error_t
```

其中：

- `S_t` 是 latent market state；
- `Z_t` 是可观测代理变量；
- `factor_t = g(Z_{t-window:t})` 是对 `S_t` 或某个 conditional parameter 的估计器；
- 机制可以最终投影到：
  - `drift / conditional mean`;
  - `diffusion / conditional volatility`;
  - `jump intensity / tail probability`;
  - `liquidity friction / impact term`;
  - `regime transition probability`;
  - `observation equation / noisy proxy`.

这既保留不同物理/数学模型的自由度，又避免所有解释停在隐喻层。

## Required Formal Chain

建议在 Ultimate / Step1 / Step2 / Step6 中强制以下链条：

```text
1. market_phenomenon
2. economic_hypothesis
3. payer_or_counterparty
4. primary_mechanism_model
5. stochastic_price_process_projection
6. formula_component_mapping
7. observable_estimator
8. target_functional
9. expected_metric_signature
10. falsification_tests
11. revision_operators
12. kill_criteria
```

每个 formal factor 至少应能回答：

- 这个因子描述什么市场行为？
- 这个行为为什么会造成可交易收益？
- 谁付钱？散户、公募、保险、国资机构、游资、量化、流动性需求方，还是风险溢价承担者？
- primary model 为什么适合？
- stochastic projection 中，信号影响 `mu`、`sigma`、`jump`、`friction`、`regime`，还是 observation equation？
- 公式里的每个关键字段和算子在模型中对应什么？
- 预期 metrics 应该是什么形状？
- 如果 metrics 不支持，应该推翻经济机制、数学模型、投影关系，还是观测器公式？

## Step-Level Contract Proposal

### Step1: Mechanism First, Formula Second

Step1 应在 `alpha_idea_master` 中新增或强化以下字段：

```json
{
  "market_process_thesis": {
    "market_phenomenon": "...",
    "economic_hypothesis": "...",
    "return_source_family": "risk_premium | information_advantage | market_structure_arbitrage | constraint_driven_arbitrage | mixed",
    "payer_or_counterparty": "...",
    "why_they_pay": "...",
    "what_must_be_true": ["..."],
    "what_would_break_it": ["..."]
  },
  "primary_mechanism_model_candidates": [
    {
      "model_family": "...",
      "why_this_model_fits": "...",
      "why_alternatives_are_less_suitable": "...",
      "state_variables": ["..."],
      "observable_proxies": ["..."],
      "target_functional": "..."
    }
  ],
  "stochastic_price_process_projection": {
    "projection_required": true,
    "price_process_skeleton": "...",
    "affected_terms": ["drift", "diffusion", "jump_intensity", "friction", "regime_transition", "observation_equation"],
    "formula_should_estimate": "...",
    "expected_return_distribution_change": "..."
  }
}
```

Step1 允许 `primary_mechanism_model_candidates` 有多个候选，但必须明确首选项和证伪方式。

### Step2: Formula-Specific Model Mapping

Step2 的 `factor_spec_master` 不应只保存 canonical formula，还应保存“模型到公式”的逐项映射。

建议新增：

```json
{
  "mechanism_math_contract_v2": {
    "selected_primary_model_family": "...",
    "selected_primary_model_reason": "...",
    "stochastic_projection": {
      "price_process_form": "...",
      "affected_price_process_terms": ["..."],
      "conditional_distribution_claim": "..."
    },
    "formula_component_mapping": [
      {
        "formula_component": "ts_rank(volume, 5)",
        "observable_proxy_for": "...",
        "model_role": "state_variable | response_variable | conditioning_variable | barrier_proxy | entropy_proxy | regime_proxy",
        "price_process_projection_role": "drift | diffusion | jump | friction | regime | observation"
      }
    ],
    "target_functional": "E[r_{t+1} | factor_t] / rank(E[r_{t+1} | factor_t]) / P(r_{t+1}>0 | factor_t) / ...",
    "expected_metric_signature": {
      "rank_ic": "...",
      "long_side_return": "...",
      "turnover": "...",
      "drawdown": "...",
      "recovery_days": "...",
      "monotonicity": "..."
    },
    "falsification_tests": ["..."],
    "initial_revision_operators": ["..."]
  }
}
```

Step2 validator 应检查：

- `selected_primary_model_family` 不是空泛标签；
- `formula_component_mapping` 覆盖所有关键字段和算子；
- 若公式没有 `volume`，不得出现 price-volume / liquidity-volume 机制；
- 若公式没有 correlation/covariance/dependence 算子，不得声称公式在估计 rolling covariance/correlation/dependence；
- stochastic projection 不能只是 `dP = mu dt + sigma dW`，必须说明字段进入哪个 term；
- `expected_metric_signature` 必须能被 Step4/5 metrics 检验。

### Step3: Implementation Must Preserve Mechanism

Step3B 不只要实现公式，还要证明实现保留 Step2 mechanism invariants：

```text
formula field mapping preserved
window / lag / rank / neutralization preserved
information_set legality preserved
primary model estimator preserved
stochastic projection role preserved
```

如果 Step3B 使用 direct Python / Polars / hybrid 实现，也必须声明生成代码没有改变 mechanism mapping。

### Step4/5: Evidence Must Be Read Against Projection

Step4/5 不应只输出 metrics，而应能支持 Step6 判断：

```text
Does observed evidence match expected metric signature?
If not, which model layer failed?
```

例如：

- IC 好但 long-side after cost 负：可能是 signal estimates mean ordering，但 turnover/friction term 被低估；
- monotonicity 好但 G10 NAV 深回撤：可能是 tail risk / regime transition 未建模；
- long-side gross 有效但 cost-adjusted 失败：可能 primary model 有效，但 observation window 太短或 execution friction 太强；
- 2016-2020 有效、2020-2024 失效：可能 payer/counterparty 或 regime state 变了。

### Step6 / Council: Revision Must Map Metrics Back To Model

Step6/Council 每轮必须回答：

```text
1. Which part of the economic hypothesis survived?
2. Which part of the primary mechanism model was falsified?
3. Which stochastic projection term was unsupported?
4. Was the formula estimating the wrong latent state or noisy proxy?
5. Should the next branch revise:
   - primary model,
   - stochastic projection,
   - observable estimator,
   - nonlinearity,
   - window,
   - regime gate,
   - scaling,
   - or formula implementation?
6. What new formula law follows from that revision?
```

Council result 必须包含：

```json
{
  "economic_hypothesis_review": "...",
  "primary_mechanism_model_review": "...",
  "stochastic_projection_review": "...",
  "model_to_formula_translation": "...",
  "metric_falsification_mapping": "...",
  "next_revision_law": {
    "law_id": "...",
    "child_formula": "...",
    "model_layer_changed": "primary_model | stochastic_projection | observable_estimator | implementation",
    "expected_metric_signature": "...",
    "kill_criteria": "..."
  }
}
```

## Council Operating Model

建议 Council taskbook 固定包含以下角色或等价任务：

1. `economic_hypothesis_reviewer`
   - 复核 return source、payer、counterparty、objective constraints；
2. `primary_model_selector`
   - 判断当前 primary model 是否贴合经济机制，必要时提出替代模型；
3. `stochastic_projection_auditor`
   - 将 primary model 投影到价格过程，明确影响 drift/diffusion/jump/friction/regime/observation；
4. `formula_estimator_translator`
   - 把模型项翻译成可执行 formula / Step3B code；
5. `metric_falsification_researcher`
   - 用 Step4/5 evidence 判断哪些模型层被支持或证伪；
6. `orchestration_synthesizer`
   - 主 agent 汇总 Council，选择 single-branch 或 multibranch，写 executable child formula。

主 agent 不能简单选择多数意见。它必须说明：

- 为什么选择某个 branch；
- 为什么放弃 sibling branches；
- 哪些 sibling branch memory 应进入下一轮；
- 哪些 prior law/formula hash 被禁止重复；
- 本轮 revision 修改的是哪一层模型。

## Good / Bad Examples

### Bad: Empty stochastic process

```text
The factor can be explained by dP = mu dt + sigma dW.
Volume affects the price process, so the formula captures price-volume microstructure.
```

问题：

- 没有说明 volume 进入 `mu`、`sigma`、`jump`、`friction` 还是 `regime`；
- 没有说明公式估计什么 latent state；
- 没有说明谁付钱；
- 不能指导 revision。

### Good: Potential barrier primary model with stochastic projection

```text
Primary model:
  potential_field_or_barrier_model.
  Volume-at-price mass creates support/resistance zones.

Economic hypothesis:
  mandate-constrained or retail anchored holders create predictable supply/demand near cost zones.

Stochastic projection:
  near barrier B_t, drift and jump intensity become state-dependent:
    dP_t/P_t = mu(distance_to_barrier, support_mass)dt
             + sigma_t dW_t
             + J(distance_to_barrier, support_mass)dN_t

Formula estimator:
  support_mass estimates the strength of the barrier;
  distance_to_barrier estimates state location.

Expected metrics:
  positive long-side return should appear when price is above high support_mass barrier;
  drawdown should be lower if barrier support is real;
  failure occurs if high support_mass increases turnover but does not reduce downside.
```

### Good: Entropy primary model with stochastic projection

```text
Primary model:
  entropy_or_information_theory.
  Sudden entropy production indicates information shock or regime destabilization.

Stochastic projection:
  entropy shock changes sigma_t and transition probability:
    P(regime_{t+1}=trend | entropy_jump, flow_direction)
    sigma_t = sigma_0 + beta * entropy_jump

Formula estimator:
  rolling sign-sequence complexity estimates entropy;
  active flow direction estimates drift sign after shock.

Expected metrics:
  entropy alone may raise volatility but not mean return;
  entropy + directional flow should improve long-side return and reduce false breakouts.
```

### Good: Alpha026-style volume/high mechanism

Do not hard-code this example, but use it as target depth.

```text
Formula:
  -max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3)

Economic hypothesis:
  high volume synchronized with high price may indicate crowded attention,
  liquidity-demand pressure, or transient impact. Taking negative exposure
  prefers stocks without recent high-volume high-price crowding.

Possible primary model:
  microstructure_response_function or volume-conditioned transient-impact process.

Stochastic projection:
  dX_t = mu_t dt
       + sigma(V_t, crowding_t)dW_t
       + impact(V_t, high_state_t, liquidity_t)dt

Formula estimator:
  correlation(ts_rank(volume), ts_rank(high)) estimates coupling between participation
  and upward price-pressure boundary.

Expected metric signature:
  IC can be positive if crowded high-volume high-price states revert;
  turnover/cost can destroy long-side economics if the state is too short-lived;
  smoothing should reduce turnover but may dilute drift if impact half-life is short.

Revision implication:
  if smoothing preserves IC but not net return, next branch should not simply repeat
  smoothing. It should test whether the model is actually an abnormal participation
  or impact-decay model, possibly adding volume normalization, regime gate, or
  nonlinear threshold.
```

## BLOCK / Validator Requirements

建议新增或强化以下 BLOCK：

### `BLOCK_MECHANISM_MODEL_UNDERSPECIFIED`

触发条件：

- 没有 primary mechanism model；
- 或 model 只是 broad label，没有 state variables、observable proxies、target functional。

### `BLOCK_STOCHASTIC_PROJECTION_EMPTY`

触发条件：

- 只写了空泛 `dP = mu dt + sigma dW`；
- 没有说明公式变量进入 drift/diffusion/jump/friction/regime/observation 哪一项；
- 没有说明条件收益分布如何改变。

### `BLOCK_FORMULA_MODEL_MAPPING_MISMATCH`

触发条件：

- 机制声称 formula 使用某类字段/算子，但公式实际没有；
- 例如无 volume 却说 volume-liquidity；
- 无 correlation/covariance/dependence 算子却说 rolling dependence estimator；
- 无 price barrier / threshold 结构却说 barrier model。

### `BLOCK_COUNCIL_DERIVATION_MISSING`

触发条件：

- Council result 只有 verdict，没有 primary model review；
- 没有 stochastic projection review；
- 没有 model-to-formula translation；
- 没有 metric falsification mapping；
- 没有可执行 child formula 或明确 `awaiting_next_derivation`。

### `BLOCK_REVISION_NOT_MODEL_LINKED`

触发条件：

- revision 只是调窗口、取反、平滑、加 rank；
- 但没有说明修改的是 primary model、stochastic projection、observable estimator、还是 implementation 层。

## Artifact / Schema Changes

建议版本化为 `mechanism_math_contract_v2`，不要破坏已有 v1 产物。

最低新增字段：

```json
{
  "mechanism_math_contract_v2": {
    "contract_version": "mechanism_math_contract_v2",
    "economic_hypothesis": {
      "return_source_family": "...",
      "payer_or_counterparty": "...",
      "why_they_pay": "..."
    },
    "primary_mechanism_model": {
      "model_family": "...",
      "model_family_justification": "...",
      "state_variables": ["..."],
      "observable_proxies": ["..."],
      "target_functional": "..."
    },
    "stochastic_price_process_projection": {
      "price_process_form": "...",
      "affected_terms": ["drift", "diffusion", "jump", "friction", "regime", "observation"],
      "conditional_distribution_claim": "...",
      "projection_limitations": ["..."]
    },
    "formula_component_mapping": [
      {
        "component": "...",
        "observable_proxy_for": "...",
        "primary_model_role": "...",
        "stochastic_projection_role": "..."
      }
    ],
    "expected_metric_signature": {
      "rank_ic": "...",
      "long_side_return": "...",
      "cost_adjusted_return": "...",
      "turnover": "...",
      "max_drawdown": "...",
      "recovery_days": "...",
      "monotonicity": "..."
    },
    "falsification_tests": ["..."],
    "revision_operators": ["..."],
    "kill_criteria": ["..."]
  }
}
```

## Acceptance Tests / Smoke Tests

### 1. No-volume formula cannot claim volume mechanism

Input formula has only close/open/high/low, no volume/amount/turnover.

Expected:

- any `volume_liquidity`, `price_volume_microstructure`, or volume-conditioned projection must BLOCK;
- unless the text explicitly says volume is unavailable and not used.

### 2. Price-volume formula cannot claim unsupported operator

Input formula uses volume and price signs, but no correlation/covariance.

Expected:

- mechanism may be price-volume or participation-related;
- but it must not say formula estimates rolling correlation/covariance/dependence.

### 3. Empty stochastic projection blocks

Input memo says only:

```text
dP = mu dt + sigma dW
```

Expected:

- validator returns `BLOCK_STOCHASTIC_PROJECTION_EMPTY`.

### 4. Primary model alternatives must be justified

Input mechanism picks stochastic process but formula is a price barrier / cost-basis structure.

Expected:

- validator requires explanation why barrier model is not primary or why stochastic process is the primary model;
- otherwise block as underspecified.

### 5. Council revision must state model layer changed

Council proposes:

```text
change window 5 to 10
```

Expected:

- BLOCK unless it explains that the window change estimates a longer impact half-life, lower noise diffusion, different regime persistence, or another explicit model-layer change.

### 6. Multibranch synthesis must preserve model diversity

If Council proposes:

- exploit: same primary model, refined estimator;
- explore: different primary model;
- explore: same model but different stochastic projection term;

Expected:

- multibranch synthesis records branch type and model layer changed;
- branch comparison records which model layer was falsified or improved;
- selected child packet carries sibling memory with model-layer outcomes.

## Production Retest Suggestion

After implementation, run a fresh production retest on one price-only/no-volume formula and one price-volume formula.

Suggested validations:

```text
1. Step1 alpha_idea_master carries mechanism_math_contract_v2 or equivalent fields.
2. Step2 factor_spec_master carries formula_component_mapping and stochastic projection.
3. main_agent_mechanism_memo validates with no generic/stale mechanism text.
4. Council taskbook requires primary model review and stochastic projection review.
5. Council result includes model-to-formula translation.
6. main_agent_council_synthesis selects revision law with model_layer_changed.
7. child executable_revision_spec carries the selected model layer and formula mapping.
8. branch_comparison records which model layer each child tested.
9. no clean data processing, no search_worker, no official promotion unless gate truly passes.
```

## Out Of Scope

This feedback does not request:

- changing clean data;
- enabling experimental performance backends;
- making stochastic process the only valid model;
- forcing every factor into a complex SDE;
- promoting any factor because the mechanism story is elegant;
- weakening Step4/5 evidence or promotion gates.

Evidence remains decisive. The new contract only makes the hypothesis and revision process auditable.

## Implementation Notes

Recommended implementation order:

1. Update `factor-forge-ultimate`, `factor-forge-researcher`, and `factor-forge-research-brain` skill text with the principle:

   ```text
   primary mechanism model + stochastic price-process projection
   ```

2. Update Step1/2 artifact schema to carry `mechanism_math_contract_v2`.

3. Update main-agent mechanism questionnaire/memo validation:

   - require selected primary model;
   - require stochastic projection;
   - require formula component mapping;
   - block generic SDE.

4. Update Council taskbook and result validator:

   - require primary model review;
   - require stochastic projection review;
   - require model-to-formula translation;
   - require model-layer-changed for revisions.

5. Update multibranch synthesis and branch comparison:

   - branch type should include model layer;
   - sibling memory should preserve model-layer outcomes.

6. Run smoke tests and one fresh production retest.

## Final Desired Behavior

After this change, any agent using Factor Forge Ultimate should naturally behave as follows:

```text
I do not start from the formula.
I start from the market behavior and payer.
I choose the best primary math/physics model.
I project it onto a stochastic price process to state what changes in future return distribution.
I treat the formula as an estimator of that model.
I read Step4/5 metrics as evidence for or against specific model layers.
I revise the model or estimator, not just the window.
I only reject after evidence falsifies the research path under the loop budget or a validator BLOCK proves the path is invalid.
```

This is the intended research standard for Codex, Humphrey, Bernard, and all future Factor Forge Council agents.
