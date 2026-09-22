# Phase O P1C 正向机制数学建模架构书

> **状态:** 待实现  
> **范围:** Step1 canonical formula intake、Step2 mechanism classifier、Step6 mechanism consumption、相关 smoke/validator。  
> **非范围:** Step3B/Step4 性能、clean data、search worker、official promotion、真实 subagent API。

## 1. 背景

Phase O P1B 已经让 Alpha019-like 公式从 `validate_step6` BLOCK 进入 `awaiting_agent_results`，但 review 发现两个核心问题仍未关闭：

1. `classifier.infer_model_family()` 只 special-case 了 Alpha019-like `slow_state_x_short_horizon_threshold`，其它公式仍可能被旧的文本启发式污染。例如 `rank(delta(close, 20))` 只有 `close` 字段，但只要旧 thesis 文本里出现 `price-volume transformations`，仍会被归到 `price_volume_microstructure`。
2. Step1 的结构化 `economic_hypothesis` 已经可以是 formula-specific，但顶层 `factor_intuition` / `return_source_hypothesis` 仍可能保留旧 generic 文本，污染 agent 和 council 读取的 headline thesis。

这说明当前实现仍不完全是“agent 理解公式后选择数学模型”，而是 Alpha019 路径修通后，旧 keyword/text fallback 仍能覆盖机制。

## 2. 设计目标

Factor Forge Ultimate 的机制数学链路必须是正向建模：

```text
source idea / canonical formula
-> formula understanding
-> two-layer economic hypothesis
-> math baseline selection
-> formula-specific model mutation
-> profit payer derivation
-> expected metric signature
-> Step6 evidence feedback
-> Council revision direction
```

validator 只做 guard，不是主要研究逻辑。系统不能靠枚举“无 volume 不准 price-volume”来过关；主路径必须先理解公式在估计什么 latent state，再根据经济假设选择合理数学对象。

## 3. 核心不变量

### 3.1 公式字段只能来自公式本身

`formula_understanding.formula_features.fields` 必须只来自：

- formula text / formula IR；
- canonical spec `required_inputs`；
- Step1/Step2 明确的 formula variables。

机制文本、旧 thesis、`mechanism_math_contract.observable_inputs` 不能创造公式字段。文本可以解释公式字段，但不能让一个 price-only 公式“拥有 volume”。

### 3.2 模型选择优先级

`infer_model_family()` 必须按以下顺序决策：

1. `formula_understanding + economic_hypothesis + math_hypothesis_candidates` 的正向选择结果。
2. formula-derived fallback，例如 price-only rank/delta 公式可落到 `stochastic_process` / `cross_sectional_statistics` / `functional_filter`，但不能由文本创造 `price_volume_microstructure`。
3. 最后才是 conservative `other`。

旧文本启发式只能在公式字段支持时细化模型，不能覆盖 formula-specific model。

### 3.3 Headline thesis 必须与结构化 hypothesis 一致

Step1 canonical formula intake 写出的以下字段必须来自 formula-specific modelling：

- `factor_intuition`
- `return_source_hypothesis`
- `final_factor.economic_logic`
- report map validation `economic_logic`

如果 nested `economic_hypothesis` 是 slow winner / threshold stochastic process，顶层 headline 不能继续写 generic `ranked price-volume transformations`。

### 3.4 Alpha019 不是唯一验收对象

Alpha019-like 是必要正例，但不能成为唯一规则。验收还必须覆盖：

- price-only generic formula + stale price-volume text；
- true price-volume formula；
- valuation/accounting formula；
- projection/residual formula；
- formula-defined unknown state。

## 4. 目标架构

### 4.1 Formula Understanding Layer

文件：

```text
/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/formula_specific.py
```

职责：

- 提取 formula fields/operators/constants/windows。
- 生成 `component_interpretations`。
- 生成 `interaction_structure`。
- 生成 `latent_state_candidates`。
- 生成可读 headline thesis。

建议公开函数：

```python
def build_formula_understanding(spec_like: dict[str, Any]) -> dict[str, Any]:
    ...

def select_math_model_from_economic_hypothesis(
    economic_hypothesis: dict[str, Any],
    math_hypothesis_candidates: list[dict[str, Any]],
    formula_understanding: dict[str, Any],
) -> dict[str, Any]:
    ...

def build_formula_specific_headline(
    economic_hypothesis: dict[str, Any],
    math_selection: dict[str, Any],
    formula_understanding: dict[str, Any],
) -> str:
    ...
```

`build_formula_specific_headline()` 应输出公开、可审查、短而准确的 thesis，例如：

```text
Formula estimates a slow winner state interacting with short-horizon pullback and sign-threshold migration; expected payoff comes from delayed trend extrapolators or temporary dislocation traders if the conditional state is monetizable.
```

### 4.2 Step1 Canonical Formula Intake

文件：

```text
/Users/humphrey/projects/factor-factory/scripts/step12_intake_common.py
```

职责：

- canonical formula intake 必须先调用 formula understanding。
- `factor_intuition` / `return_source_hypothesis` 不再从旧 generic `initial_return_source_hypothesis` 直接取值。
- 旧 `initial_return_source_hypothesis` 可保留为 legacy/debug 字段，但不能作为 headline source。

目标 artifact：

```json
{
  "factor_intuition": "<formula-specific headline>",
  "return_source_hypothesis": "<formula-specific headline>",
  "economic_hypothesis": {...},
  "math_hypothesis_candidates": [...],
  "formula_understanding": {...},
  "economic_to_math_modelling": {
    "selected_baseline_model": {...},
    "model_mutations": [...],
    "profit_payer_derivation": {...},
    "expected_metric_signature": {...},
    "metric_feedback_rules": [...]
  }
}
```

### 4.3 Step2 Mechanism Classifier

文件：

```text
/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/classifier.py
```

职责：

- `infer_model_family()` 必须首先读取 Step1 的 formula understanding / economic hypothesis / math candidates。
- 只要 `select_math_model_from_economic_hypothesis()` 返回明确 model family 且不是 `other`，应采用该 family。
- family 映射可以规范化，例如：
  - `ranked_price_state_process` -> `stochastic_process`
  - `canonical_formula_state_process` -> `stochastic_process` 或 `other`，视公式证据；
  - `ranked_price_volume_state_process` -> `price_volume_microstructure`，但必须有 formula-derived volume/liquidity field。

旧 `_text_blob()` 启发式只能作为最后 fallback，且必须用 formula-derived `has_price` / `has_volume`。不能使用 text token 让 absent field 变成 present field。

### 4.4 Step6 Mechanism Consumption

文件：

```text
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_step6.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_step6.py
```

职责：

- Step6 优先消费 `mechanism_math_contract.source_economic_hypothesis`、`source_math_hypothesis_candidates`、`formula_understanding`、`economic_to_math_model_selection`。
- Step6 研究 brief 和 council packet 应沿用这些字段，不重新用 generic text 生成机制。
- validator 继续做 consistency guard，但不得成为唯一正确性来源。

## 5. 模型选择原则

数学工具不是固定映射，而是由经济机制和公式结构共同选择。

示例：

| 经济机制 | 公式结构证据 | 合理 baseline | 可能 mutation |
|---|---|---|---|
| earnings / FCF / valuation payer | accounting / valuation fields | `valuation_identity` / DCF / residual income | growth persistence, discount-rate shock |
| slow winner + short threshold | long return window + short delta/delay + sign | `stochastic_process` | threshold boundary, state interaction |
| price-volume crowding | formula-derived volume/amount/turnover plus price-volume dependence operator | `price_volume_microstructure` | transient impact decay, liquidity-demand state |
| projection residual | explicit neutralize/residualize/projection | `linear_factor_projection` | orthogonal residual state |
| rank dependence without volume | rank/delta/rolling price state | `stochastic_process` / `cross_sectional_statistics` | rank-state conditional distribution |

关键点：表格不是硬编码映射。它是模型选择的候选空间。每个 factor 必须写出 `why_selected`、payer derivation、observable estimator、target functional。

## 6. 验收标准

### 6.1 必须通过的正例

Alpha019-like:

- Step1 headline 不含旧 generic price-volume thesis。
- Step1 `economic_hypothesis.second_layer.subtype` 包含 slow winner / short threshold。
- Step2 `mechanism_math_contract.model_family=stochastic_process`。
- Step6 `mechanism_formula_consistency.status=PASS`。
- Ultimate loop `--council-mode auto` 停在 `awaiting_agent_results`。

True price-volume formula:

- formula-derived fields 包含 volume/amount/turnover。
- 有 price-volume dependence operator 或明确流动性状态。
- 才可选择 `price_volume_microstructure`。

Price-only polluted-text formula:

- formula: `rank(delta(close, 20))`
- stale text: `ranked price-volume transformations`
- 结果不得为 `price_volume_microstructure`。

### 6.2 必须通过的验证命令

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/formula_specific.py \
  factor_factory/mechanism_math/classifier.py \
  scripts/step12_intake_common.py \
  skills/factor-forge-step2/scripts/run_step2.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  scripts/run_step12_hypothesis_contract_smoke.py \
  scripts/run_mechanism_math_contract_smoke.py

python3 scripts/run_step12_hypothesis_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_step12_phase_o_p1c_positive_modelling

python3 scripts/run_mechanism_math_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_mechanism_math_phase_o_p1c_positive_modelling

python3 scripts/run_step6_intelligence_acceptance.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_acceptance_phase_o_p1c
```

如修改 Step6/Ultimate installed skill 文件，必须同步并 diff clean：

```bash
diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-step6 \
  /Users/humphrey/.codex/skills/factor-forge-step6

diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate \
  /Users/humphrey/.codex/skills/factor-forge-ultimate
```

## 7. 明确禁止

- 不要用 forbidden keyword list 代替正向建模。
- 不要只 special-case Alpha019。
- 不要让 mechanism text 创造 formula 中不存在的 observable field。
- 不要让 deterministic scaffold 伪装成 agentic council。
- 不要改 Step3B/Step4 性能路径。
- 不要处理 clean data。
- 不要执行 search worker。
- 不要写 official promotion。

