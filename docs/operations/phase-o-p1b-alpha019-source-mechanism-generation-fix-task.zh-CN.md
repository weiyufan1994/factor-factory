# Phase O P1B Formula-Specific Economic-to-Math Modelling Fix 任务书

> **执行对象:** Factor Factory coder thread  
> **审查对象:** reviewer thread  
> **范围:** Phase O P1B。修正 Step1/Step2/Step6 的机制生成源头，让 agent 根据公式结构、作者意图、economic hypothesis 主动选择准确数学建模，而不是靠枚举禁止词过滤错误机制。

## 核心原则

这不是一个“无 volume 就禁止 price-volume”的补丁任务。

真正目标是：

```text
source idea / canonical formula
-> formula feature understanding
-> economic hypothesis
-> math baseline selection
-> model mutation for this formula
-> profit payer derivation
-> expected metric signature
-> Step6 evidence feedback
-> council revision direction
```

validator 只做兜底。主逻辑必须是正向建模：agent 要理解公式在估计什么 latent state，谁可能为这个 state 付钱，为什么付钱，以及用什么数学对象表达这个赚钱机制。

## 复测失败背景

Fresh report id：

```text
ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_20260518
```

命令：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_20260518 \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

结果：

- `final_outcome=failed`
- `stop_reason=ultimate_wrapper_failed`
- 失败点：`validate_step6`
- Step6 blocker：

```text
BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION:
formula has no volume input but mechanism text claims volume dependence: ['price-volume']
```

这个 blocker 是正确的，但它只说明 validator 抓住了错误。真正需要修的是上游机制生成：Step1/Step2 仍没有理解 Alpha019 的公式结构。

## Alpha019 应被怎样理解

Alpha019 canonical formula：

```text
multiply(
  negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))),
  plus(1, rank(plus(1, sum(returns, 250))))
)
```

公式结构理解：

- `sum(returns, 250)`：长期 winner / trend / accumulated return state。
- `close - delay(close, 7)` 与 `delta(close, 7)`：短期价格变化 / pullback / reversal / dislocation state。
- `sign(...)`：阈值边界、状态切换、bucket migration，不是平滑线性暴露。
- `rank(...)`：横截面 rank-state，表达相对位置和 crowding / conditional distribution，而不是自动等于 price-volume。
- 外层乘法：长期状态与短期状态交互，即 slow state × short-horizon state interaction。

经济机制候选：

```text
长期强势资产中的短期反转/回撤/状态切换，可能来自趋势跟随者的迟滞修正、短期冲击衰减、或 winner 状态下边际交易者的过度反应。
```

数学 baseline 候选：

- `stochastic_process`: price/return process with slow trend state and short-horizon reversal/dislocation component。
- `jump_threshold`: because `sign` creates a discontinuous state boundary。
- `copula_rank_dependence`: rank transform can be used as cross-sectional conditional state, but only after economic mechanism justifies it。

更合适的 model synthesis 可以是：

```text
S_i,t = slow_winner_state_i,t × threshold(short_horizon_pullback_i,t)

P_i,t = F_i,t + M_i,t + I_i,t + epsilon_i,t
M_i,t: slow trend / winner state
I_i,t: short-horizon temporary dislocation or pullback state

E[r_i,t+1 | S_i,t, F_t]
```

profit payer derivation 应写清楚：

- payer：长期 winner 中追随趋势但在短期状态切换时反应滞后的边际交易者，或在短期回撤/冲击中提供错误方向流动性的交易者。
- why pay：他们把 slow winner state 线性外推，或在 threshold crossing 后迟滞调仓，导致下一期收益对 `slow × short-state` 条件状态有可预测性。
- how I profit：公式估计这个条件状态，若 metrics 支持，则 long-side 或 revised expression 捕捉其均值回归/延续 payoff；若 metrics 不支持，则 council 应 mutate sign、horizon、state interaction 或 kill。

## 目标

实现一个正向的 formula-specific modelling layer，使 Step1/Step2/Step6 都围绕以下 artifact 工作：

```json
{
  "formula_understanding": {
    "formula_features": {...},
    "component_interpretations": [...],
    "interaction_structure": "slow_state_x_short_state_threshold",
    "latent_state_candidates": [...]
  },
  "economic_to_math_modelling": {
    "economic_hypothesis": {...},
    "selected_baseline_model": "stochastic_process | jump_threshold | valuation_identity | state_space | ...",
    "why_selected": "...",
    "model_mutations": [...],
    "profit_payer_derivation": {...},
    "expected_metric_signature": {...},
    "metric_feedback_rules": [...]
  }
}
```

这不是 LLM hidden chain-of-thought。它是公开、可审查、可沉淀到知识库的研究结论和建模摘要。

## 设计要求

### A. 新增或扩展 formula understanding 层

建议修改：

- `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/formula_specific.py`
- `/Users/humphrey/projects/factor-factory/scripts/step12_intake_common.py`

实现目标：

1. 从 formula text / formula IR / required fields / operators / constants 提取结构。
2. 生成 `component_interpretations`，至少覆盖：
   - long window return sum
   - short delay / delta
   - sign / threshold
   - rank / cross-sectional state
   - multiplication / interaction
3. 生成 `interaction_structure`，例如：
   - `slow_state_x_short_horizon_threshold`
   - `price_volume_dependence`
   - `valuation_ratio_state`
   - `projection_residual_state`
4. 生成 `latent_state_candidates`，不靠固定 family 标签，而是解释公式可能估计的经济状态。

Alpha019-like 正例必须得到：

```text
interaction_structure = slow_state_x_short_horizon_threshold
latent_state_candidates includes slow winner/trend state, short-horizon pullback/reversal/dislocation, threshold migration
```

### B. Step1 canonical formula intake 要用 formula understanding 写 economic hypothesis

修改：

- `/Users/humphrey/projects/factor-factory/scripts/step12_intake_common.py`

当前问题不是“删 price-volume”，而是 Step1 没有根据公式生成正确 thesis。

Step1 对 canonical formula 应：

1. 先解析公式结构。
2. 根据结构生成 `economic_hypothesis` 两层：
   - 第一层：`risk_premium / information_advantage / market_structure_arbitrage / mixed`
   - 第二层：公式特异的 payer + why they may pay。
3. 根据 economic hypothesis 生成 `math_hypothesis_candidates`。
4. `factor_intuition` / `return_source_hypothesis` / `final_factor.economic_logic` 必须来自 formula understanding，而不是统一模板。

Alpha019-like Step1 应生成类似：

```json
{
  "economic_hypothesis": {
    "macro_return_source": "mixed",
    "second_layer": {
      "subtype": "slow_winner_state_short_horizon_reversal_or_threshold_migration",
      "expected_counterparty_or_payer": "trend extrapolators, delayed updaters, or short-horizon liquidity/dislocation traders around winner-state pullbacks",
      "why_they_may_pay": "they extrapolate the slow winner state or react late to threshold crossings, creating conditional next-period payoff when the short-horizon state reverses or migrates"
    }
  },
  "math_hypothesis_candidates": [
    {
      "model_family": "stochastic_process",
      "process_or_distribution_hypothesis": "return process with slow trend state and short-horizon reversal/dislocation component",
      "model_mutation": "add threshold boundary induced by sign transform",
      "target_functional": "E[r_i,t+1 | slow_state_i,t, short_state_i,t, threshold_i,t]"
    }
  ]
}
```

### C. Step2 mechanism classifier 要选择模型，不是文本 keyword 归类

修改：

- `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/classifier.py`

要求：

1. `infer_model_family()` 应优先使用 formula understanding / Step1 math_hypothesis_candidates。
2. 如果 Step1 给了 credible `math_hypothesis_candidates[0].model_family`，Step2 应把它映射到 mechanism contract family。
3. 不允许仅因为 thesis text 出现某些泛化词，就覆盖 formula-specific model。
4. 对 Alpha019-like：
   - selected family 应为 `stochastic_process` 或明确 composite/threshold-compatible family；
   - 不应选 `price_volume_microstructure`。

建议新增 internal API：

```python
def build_formula_understanding(spec_like: dict[str, Any]) -> dict[str, Any]: ...

def select_math_model_from_economic_hypothesis(
    economic_hypothesis: dict[str, Any],
    math_hypothesis_candidates: list[dict[str, Any]],
    formula_understanding: dict[str, Any],
) -> dict[str, Any]: ...
```

如果不新增文件，也可以在 `formula_specific.py` 中实现，classifier 调用。

### D. mechanism_math_contract 要表达具体建模

Alpha019-like Step2 contract 应包含：

```json
{
  "model_family": "stochastic_process",
  "math_toolkits": ["probability_theory", "stochastic_process_calculus", "time_series_and_filtering", "statistics"],
  "state_or_object": "slow winner state interacting with short-horizon reversal/dislocation threshold state",
  "factor_as_estimator": "the formula estimates a cross-sectional conditional state formed by long-window return rank and short-horizon sign-threshold price movement",
  "process_hypothesis": "returns follow a stochastic process with slow trend state and short-horizon reversal/dislocation component; sign transform creates threshold migration",
  "conditional_distribution_hypothesis": "r_i,t+1 | F_t, slow_state_i,t, short_state_i,t, threshold_i,t",
  "observable_estimator": "sum(returns,250), close-delay(close,7), delta(close,7), sign threshold, cross-sectional rank",
  "mechanism_falsification_tests": [...],
  "revision_operators": [...]
}
```

### E. validator 只做兜底，不作为主修复

可以增强 validator，但不能用 validator 代替生成器。

允许增加：

- Step2-level consistency blocker：如果 selected model contradicts formula understanding，BLOCK。
- Token 示例：

```text
mechanism_math_model_formula_understanding_mismatch
```

但验收重点是 generated contract 自身正确，而不是只靠 blocker。

## 必须新增 smoke

### 1. Step12 formula-specific source mechanism smoke

文件：

- `/Users/humphrey/projects/factor-factory/scripts/run_step12_hypothesis_contract_smoke.py`

新增 case：

```text
alpha019_like_formula_specific_modelling_pass
```

构造 Alpha019-like canonical formula，跑 Step1 standardize / validate / Step2 wrapper。

断言：

- Step1 `economic_hypothesis.second_layer.subtype` 包含 slow winner / short horizon / threshold/reversal 语义。
- Step1 `math_hypothesis_candidates[0].model_family` 是 formula-specific，不是 generic template。
- Step2 `mechanism_math_contract.model_family == stochastic_process`，或 reviewer认可的 equivalent formula-specific family。
- Step2 contract 的 `state_or_object`、`factor_as_estimator`、`process_hypothesis`、`conditional_distribution_hypothesis` 都包含 Alpha019-like formula components。
- Step2 contract source hypotheses 与 research_contract 一致。

### 2. Mechanism math classifier smoke

文件：

- `/Users/humphrey/projects/factor-factory/scripts/run_mechanism_math_contract_smoke.py`

新增 case：

```text
alpha019_slow_winner_short_reversal_stochastic_process_pass
```

直接调用 classifier，期望 model family 为 `stochastic_process`，并检查 state/process/estimator 不是 generic。

### 3. Fresh ultimate loop smoke or targeted integration smoke

可以新增独立 smoke，也可以在 coder 手工验证中跑 fresh id。

必须证明：

```text
final_outcome = awaiting_agent_results
council_status = awaiting_agent_results
revision_council.effective_mode = agentic_dispatch_manifest
agentic_taskbook exists
agentic_dispatch_manifest exists
```

## 验证命令

```bash
python3 -m py_compile \
  scripts/step12_intake_common.py \
  factor_factory/mechanism_math/formula_specific.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_step12_hypothesis_contract_smoke.py \
  scripts/run_mechanism_math_contract_smoke.py
```

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_step12_phase_o_p1b_formula_modelling
```

```bash
python3 scripts/run_mechanism_math_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_mechanism_math_phase_o_p1b_formula_modelling
```

```bash
python3 scripts/run_step6_intelligence_smoke.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_phase_o_p1b_formula_modelling
```

```bash
python3 scripts/run_step6_intelligence_acceptance.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_acceptance_phase_o_p1b_formula_modelling
```

Fresh integration retest：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_P1B_<YYYYMMDDHHMM> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

期望：

- wrapper 不在 `validate_step6` 失败。
- `mechanism_formula_consistency.status=PASS`。
- `final_outcome=awaiting_agent_results`。
- `revision_council.status=awaiting_agent_results`。
- agentic dispatch artifacts 存在。

## 验收标准

Reviewer 必须确认：

- 不是靠扩大 forbidden word list 过关。
- Step1 的 economic hypothesis 是公式特异的。
- Step2 的 math model 是由 Step1 economic hypothesis + formula understanding 推导出来的。
- Alpha019-like contract 明确描述：slow winner / long-window state、short-horizon reversal/dislocation、sign threshold、rank-state。
- Fresh Alpha019-like ultimate loop 进入 agentic dispatch pause，而不是 Step6 validate fail。
- Step6/Council/promotion gate 没被削弱。
- 无 clean data processing、search worker、official promotion、真实 subagent API。

## Coder 回复格式

```text
已完成 Phase O P1B formula-specific economic-to-math modelling fix。

修改文件：
- ...

核心修复：
- Step1 canonical formula intake 根据 formula understanding 生成 economic hypothesis。
- Step2 classifier 根据 economic hypothesis + formula understanding 选择 math baseline/model mutation。
- Alpha019-like 现在生成 slow winner × short-horizon threshold/reversal 的 stochastic_process contract。
- validator 仅作为 consistency guard，没有靠 forbidden-list 修复。

新增 smoke：
- alpha019_like_formula_specific_modelling_pass: PASS
- alpha019_slow_winner_short_reversal_stochastic_process_pass: PASS
- fresh ultimate loop auto dispatch pause: PASS

验证：
- py_compile PASS
- Step12 smoke ACCEPT: <path>
- mechanism math smoke ACCEPT: <path>
- Step6 intelligence smoke ACCEPT
- Step6 intelligence acceptance: STEP6_INTELLIGENCE_ACCEPTED
- fresh Alpha019-like loop: final_outcome=awaiting_agent_results, council_status=awaiting_agent_results

确认未做：
- 未处理 clean data
- 未执行 search worker
- 未写 official promotion
- 未接真实 subagent API
- 未改 Step3B/Step4 性能路径
```
