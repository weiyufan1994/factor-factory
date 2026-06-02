# Factor Forge Dirac-Style Research Contract

## 目标

Factor Forge 的因子研究不应只回答“这个公式历史上有没有 IC”，而要回答：

```text
这个因子从哪个市场结构方程、参与者约束、行为反馈环或经验不变性中被推出？
公式估计的是哪一个 latent/model state？
实证指标是否支持这个 state 对未来收益分布的影响？
如果公式推出反直觉结果，应该归类为错误、数据伪影、实现伪影、可交易异常，还是新因子种子？
```

这套 contract 的目标不是把金融市场伪装成物理世界，而是借鉴 Dirac-style 的研究纪律：

```text
先写结构关系，再推导可观测含义，再做实证证伪。
```

## 约束层级

每个因子都应声明其 `research_equation_status`。不要把经验规律伪装成严格恒等式。

| Level | Status | 含义 | 示例 |
| --- | --- | --- | --- |
| 0 | `strict_identity` | 数学或会计上必须成立 | 会计恒等式、清算恒等式、组合权重恒等、SDF/Euler 定价恒等 |
| 1 | `institutional_constraint` | 由制度、合同、风控、资产负债表或市场规则强制产生 | T+1、涨跌停、赎回压力、指数跟踪、风控减仓 |
| 2 | `behavioral_feedback` | 由稳定行为偏误或组织约束形成的动态关系 | 处置效应、追涨杀跌、考核压力、拥挤踩踏 |
| 3 | `empirical_invariance` | 跨资产、跨市场或跨尺度反复出现的经验结构 | 平方根冲击、波动率聚集、幂律尾部、跨频共振 |
| 4 | `research_conjecture` | 尚未充分验证，但能生成可证伪假设的结构猜想 | Dirac sea 类比、负能头寸海、异常解因子种子 |

Level 0 可以作为硬约束。Level 1-4 可以作为研究方程，但必须声明适用范围、假设和证伪方式。

## Canonical Research Equation

每个因子应尽量写成一个可审查的结构方程：

```text
observable_factor_t = estimator(latent_state_t, F_t) + measurement_noise_t

E[r_{t+h} | F_t, observable_factor_t]
  = mechanism_payoff(latent_state_t)
  - trading_cost(turnover_t)
  - volatility_drag(sigma_t)
  - drawdown_capital_cost(path_t)
  - capacity_or_liquidity_penalty(size_t)
  + residual_noise_t
```

如果主模型不是 stochastic process，也仍然需要把股票价格过程作为 benchmark/projection 层：

```text
dS_t / S_t = mu(state_t, F_t) dt
           + sigma(state_t, F_t) dW_t
           + jump(state_t, F_t) dN_t
           - friction(state_t, F_t) dt
```

这个过程不一定是主模型；它是用来检查：

- 因子估计的 state 影响 drift、diffusion、jump、friction 还是 observation equation；
- T+0/T+1 中高频因子是否能解释短期收益分布变化；
- 当主模型无法推理时，是否能通过 conditional return process 给出 benchmark implication；
- metric evidence 是否支持该 projection。

## Step1/Step2 Contract

Step1/Step2 必须区分：

```text
economic_hypothesis
primary_mathematical_model
benchmark_math_tools
stochastic_price_process_projection
formula_as_observable_estimator
formula_implied_information
```

规则：

1. 不允许默认所有因子都是 stochastic process。
2. 主模型应由经济假设决定，例如：
   - valuation identity
   - microstructure response function
   - behavioral constraint model
   - inventory/execution model
   - regime switching model
   - information theory
   - dimensional/scaling analysis
   - copula/dependence model
   - wavelet/spectral model
3. 即使主模型不是 stochastic process，也要保留 stochastic price-process projection 作为 benchmark。
4. `formula_implied_information` 不能复述 raw field 或公式调用，必须说明公式恢复的 latent/model state。

## Formula-Implied Information Review

每个 mechanism contract 必须有：

```json
{
  "formula_implied_information": {
    "structural_constraints": [],
    "latent_state_inferred_by_formula": "",
    "estimator_interpretation": "",
    "why_not_raw_field_restatement": "",
    "price_process_connection": ""
  },
  "formula_implied_information_review": {
    "reviewer_task": "formula_implied_information_reviewer",
    "negative_solution_policy": "do_not_discard_until_classified",
    "unexpected_implications": []
  }
}
```

Validator 应阻断：

- 缺少 `formula_implied_information`;
- latent state 只是 `close`、`volume`、`rank(close)` 或公式复述；
- 机制文本引用了公式中不存在的输入，且没有结构化 justification；
- 出现 unexpected implication 但没有分类；
- `tradable_anomaly` 或 `new_factor_seed` 没有 branch law、expected metric signature 和 kill criteria。

## Dirac-Style Anomaly Review

异常解不是默认错误。每个 unexpected implication 必须分类：

```text
bug
data_artifact
implementation_artifact
benign_model_implication
tradable_anomaly
new_factor_seed
theory_rejected
```

对于 `tradable_anomaly` 和 `new_factor_seed`，必须写：

```json
{
  "child_formula_or_law": "",
  "expected_metric_signature": [],
  "kill_criteria": []
}
```

示例：

```text
如果公式推出“负号方向才有收益”，不能直接说公式错。
必须判断这是实现符号错误、样本伪影、原始经济假设错了，还是新 latent state。
```

## Research Equation 模板

`mechanism_math_contract_v2` 顶层必须写入 `research_equation`：

```json
{
  "research_equation": {
    "equation_text": "",
    "equation_status": "strict_identity|institutional_constraint|behavioral_feedback|empirical_invariance|research_conjecture",
    "assumptions": [],
    "validity_scope": {
      "market": "",
      "frequency": "",
      "regime": "",
      "participant_structure": ""
    },
    "symmetry_or_constraint": "",
    "symmetry_breaking_mechanism": "",
    "latent_state": "",
    "observable_estimator": "",
    "expected_metric_signature": [],
    "falsification_tests": [],
    "kill_criteria": []
  }
}
```

`equation_status` 只能是：

```text
strict_identity
institutional_constraint
behavioral_feedback
empirical_invariance
research_conjecture
```

`validity_scope` 必须包含 `market`、`frequency`、`regime`、
`participant_structure`。`strict_identity` 必须有 identity/accounting/
clearing/SDF/Euler/cash-flow/balance-sheet/no-arbitrage 等硬约束语言。

## T+0/T+1 Stochastic Benchmark

主模型不一定是 stochastic process，但交易对象是股票价格，因此
`mechanism_math_contract_v2` 顶层必须写：

```json
{
  "t0_t1_stochastic_benchmark": {
    "benchmark_required": true,
    "horizon": "T+0/T+1 or report_horizon",
    "affected_terms": ["drift", "diffusion", "jump", "friction", "regime_transition", "observation_equation"],
    "conditional_distribution_claim": "",
    "benchmark_implication": "",
    "when_primary_model_cannot_infer": "",
    "falsification_tests": []
  }
}
```

`affected_terms` 只能从 drift、diffusion、jump、friction、
regime_transition、observation_equation 中选择。泛化的
`dS = mu S dt + sigma S dW` 不能作为有效 benchmark。

## Step6 Research Equation Review

Step6 `mechanism_analysis` 必须写：

```json
{
  "research_equation_review": {
    "reviewer_task": "research_equation_reviewer",
    "equation_status": "",
    "equation_supported_by_metrics": "supported|challenged|under_specified",
    "metric_links": {
      "rank_ic": "",
      "long_side_return": "",
      "cost_adjusted_return": "",
      "turnover": "",
      "volatility_drag": "",
      "max_drawdown": "",
      "recovery_days": ""
    },
    "failed_equation_component": "none|assumptions|latent_state|observable_estimator|price_process_projection|implementation_contract|trading_cost|drawdown_geometry",
    "revision_implication": ""
  }
}
```

泛化文本如 “metrics support the model” 不能通过 validator。`equation_status`
必须与 `mechanism_math_contract_v2.research_equation.equation_status` 对齐。

## Council Research Equation Revision

Revision Council proposal 必须写：

```json
{
  "research_equation_revision": {
    "equation_component_target": "assumptions|latent_state|observable_estimator|price_process_projection|implementation_contract|trading_cost|drawdown_geometry",
    "equation_change": "",
    "expected_metric_signature_change": [],
    "falsification_tests": []
  }
}
```

缺失该字段时 validator 返回：

```text
BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_MISSING
```

## Drawdown Geometry

Step4/self-quant 在 long-side NAV 可用时输出：

```text
long_side_drawdown_area
long_side_normalized_drawdown_area
long_side_max_drawdown_episode_area
long_side_recovery_pain_area
cost_adjusted_long_side_drawdown_area
cost_adjusted_long_side_normalized_drawdown_area
cost_adjusted_long_side_max_drawdown_episode_area
cost_adjusted_long_side_recovery_pain_area
```

Step6 `factor_business_review.drawdown_geometry` 解释这些字段。面积表示
underwater investor pain；它是风险预算的辅助诊断，不替代 max drawdown 或
recovery days。

## 微观结构与行为反馈环

这类研究方程通常不是严格恒等式，但可以是高价值假设。

示例：

```text
forced_sell_pressure_t
  = f(price_vs_cost_basis_t, trapped_position_density_t, liquidity_t)
  - absorption_capacity_t
  - time_decay_t
```

可观测 estimator：

```text
resistance_penetration_strength
  = breakout_volume / post_break_pullback_depth
```

预期 signature：

- 穿越后浅回撤组未来收益更强；
- 控制成交量和波动后仍有效；
- 高换手但不回撤表示卖压被高信念资金吸收；
- 熊市或低流动性 regime 下信号弱化。

## 类 Dirac 结构不变性

经验不变性可作为 benchmark，不是硬真理。

可用工具：

- square-root impact law;
- volatility clustering;
- power-law tail / Hill estimator;
- cross-frequency IC stability;
- dimensional/scaling analysis;
- cross-asset isomorphism;
- invariance under price scale, liquidity bucket, market regime, or frequency transformation.

使用原则：

```text
如果因子声称抓住结构性 alpha，它至少应在某些变换下保留方向、符号或尺度关系。
如果只在一个频率、一个 regime、一个量纲选择下成立，必须降级为 local feature。
```

## 指标必须回扣模型层

Step6 的指标解释必须映射到：

```text
economic_hypothesis
primary_mechanism_model
stochastic_projection
observable_estimator
implementation_contract
```

例如：

- IC 方向错误：可能是 observable estimator 符号错、经济假设反了，或实现错误。
- long-side 为负：当前 mandate 下不可 promote，即使 long-short spread 好。
- turnover 高：不是单纯性能问题，而可能说明 state half-life 太短。
- drawdown 深且恢复慢：说明收益来源无法支付资本占用和持有人体验成本。

## 因子的财务表现指标

现有业务类比：

```text
revenue = long-side expected return
COGS = turnover * cost_rate
volatility_drag = -0.5 * sigma^2
capital_impairment = max_drawdown
payback = recovery_days
```

应扩展为：

```text
net_arithmetic_return
net_geometric_growth = mean_return - trading_cogs - 0.5 * sigma^2
risk_capital_required = VaR/ES or volatility proxy
capital_charge = risk_capital_required * required_return_on_risk_capital
drawdown_provision = abs(max_drawdown) / expected_drawdown_cycle_years
economic_net_alpha = mean_return - trading_cogs - 0.5*sigma^2 - capital_charge - drawdown_provision
```

## Drawdown Geometry

最大回撤不只看最深点，还应看水下面积。

定义：

```text
H_t = max_{s <= t} NAV_s
underwater_t = max(0, (H_t - NAV_t) / H_t)

drawdown_area = sum_t underwater_t
normalized_drawdown_area = drawdown_area / total_days

max_drawdown_episode_area = max over drawdown episodes sum_t underwater_t
recovery_pain_area = sum_{t = trough}^{recovery} underwater_t
```

解释：

- `max_drawdown`: 最深一刀；
- `recovery_days`: 疼了多久；
- `drawdown_area`: 总痛苦面积；
- `max_drawdown_episode_area`: 最糟一次痛苦面积；
- `recovery_pain_area`: 从最痛点到恢复的体验成本。

面积越小，说明持有人体验越好。主评价建议使用完整 `drawdown_area`，因为投资者从跌破高水位开始已经在水下；`recovery_pain_area` 作为补充指标，衡量最大痛点之后的恢复质量。

## 当前实现状态摘要

截至本文件记录时：

- Step1/Step2 已要求区分 primary mathematical model 和 stochastic benchmark projection；
- mechanism_math_contract_v2 已有 `formula_implied_information`;
- validator 已阻断 formula-implied raw-field restatement；
- validator 已要求 `formula_implied_information_review` 和 unexpected implication 分类；
- Step6 validator 已要求 metrics 回扣模型层；
- Step6 已有 turnover COGS、volatility drag、max drawdown、recovery days 的业务评价；
- 已硬化：`research_equation` 分层字段、T+0/T+1 stochastic benchmark 字段、drawdown area / recovery pain area 指标、equation quality rubric、discovery queue、prompt contract smoke、对应 validator 和 smoke。

## Equation Quality Rubric

`research_equation` 不只要分类，还要说明质量来源：

```json
{
  "evidence_tier": "logical_identity|institutional_rule|documented_microstructure_law|cross_asset_empirical_invariance|single_market_empirical_regular|report_specific_hypothesis",
  "audit_basis": [],
  "participant_constraint_loop": {
    "payer": "",
    "constraint": "",
    "repeat_mechanism": "",
    "failure_condition": ""
  },
  "demotion_triggers": [],
  "quality_score": 0
}
```

Validator 规则：

- `strict_identity` 必须有 `audit_basis`；
- `behavioral_feedback` 必须有 `participant_constraint_loop.repeat_mechanism`；
- `empirical_invariance` 必须有明确 `validity_scope`；
- `research_conjecture` 不能在未证实前授权 promotion；
- `demotion_triggers` 必须来自已知触发器，例如 participant structure change、liquidity regime change、metric signature mismatch 或 cross-sample failure。

## Equation-To-Factor Discovery Queue

类 Dirac 方法也用于发现因子，但 discovery candidate 只能是 review packet，不是自动执行任务。

队列 JSON：

```json
{
  "version": "factorforge_dirac_discovery_queue_v1",
  "report_id": "",
  "source": "step6_anomaly_review|explicit_discovery_request",
  "auto_run_allowed": false,
  "candidates": [],
  "validation_blocks": {}
}
```

候选项必须包含：

- `source_equation_id`
- `observable_inputs`
- `measurement_equation`
- `expected_metric_signature`
- `expected_cost_risk_profile`
- `stochastic_benchmark_terms`
- `falsification_tests`
- `branch_action=review_only|human_approval_required`
- `auto_run_allowed=false`

任何 equation-derived candidate 都不得自动启动 Step2/Step3/Step4。只有现有 run loop 或人工批准的 branch request 可以把候选项转为正式因子研究。

## LLM Prompt Pack

Repo prompt references 必须包含四个命名 prompt block：

- `Dirac-Style Step1 Mechanism Extraction Prompt`
- `Dirac-Style Step2 Factor Spec Prompt`
- `Dirac-Style Step6 Council Prompt`
- `Equation-To-Factor Discovery Prompt`

Prompt smoke 检查这些 prompt 是否要求：

- classified research equation；
- `equation_status`、`assumptions`、`validity_scope`；
- `primary_mathematical_model`；
- `t0_t1_stochastic_benchmark`；
- `observable_detector_contract`；
- `formula_implied_information`；
- `expected_metric_signature`；
- `falsification_tests`；
- `kill_criteria`。

Prompt 不得诱导模型只解释公式、默认 stochastic process 是 primary model、用 IC alone 证明因子，或把 `formula_text` 当作 mechanism。

## 后续任务边界

下一轮 coder 任务应只做以下事项：

1. 把 `research_equation` 字段加入 mechanism contract / Step6 Council。
2. 把 stochastic projection 明确扩展为 T+0/T+1 benchmark，尤其服务中高频因子。
3. 把 drawdown geometry 指标加入 Step4/Step6 输出。
4. 加 validator 和 smoke，阻断缺失字段、泛泛等式、未分类 anomaly、指标未回扣模型层。

不要在这轮任务中：

- 修改 Step3/Step4 性能路径；
- 修改 Data API 清洗职责；
- 用数学 contract 绕过真实 Step4/5 evidence；
- 把经验不变性误标为 strict identity。
