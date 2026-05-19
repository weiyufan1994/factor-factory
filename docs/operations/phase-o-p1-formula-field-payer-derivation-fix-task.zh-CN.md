# Phase O P1 Formula Field / Payer Derivation Fix 任务书

> **执行对象:** Factor Factory coder thread  
> **审查对象:** reviewer thread  
> **范围:** Phase O P1 窄修。只修公式字段一致性与 profit payer derivation 合同，不改 Step3/Step4 性能、不跑真实因子、不接真实 subagent API、不改 promotion gate。

## 目标

关闭 Phase O review 的两个 P1：

1. `formula_features()` 不能把 `mechanism_math_contract.observable_inputs` 当成公式真实字段，否则错误机制合同可以把无 `volume` 公式伪装成含 `volume`，绕过 Alpha019-like field contradiction。
2. `formula_specific_derivation.profit_payer_derivation` 不能接受泛化占位句，必须从经济假设、数学模型选择、公式组件和可检验 payoff 逻辑中显性推出“谁付钱、为什么付钱、我如何获利”。

## 不做内容

- 不改 Step3B / Step4 语义。
- 不处理 `data/clean`。
- 不执行 search worker。
- 不写 official promotion。
- 不接真实 OpenClaw/Codex/remote subagent API。
- 不跑 Alpha017 / Alpha018-022 full benchmark。
- 不把 deterministic scaffold 伪装成 formal agentic council。
- 不扩大到 N.3/N.4/N.5 性能实验。

## 背景问题

### P1-1: 机制合同污染公式字段

当前 `factor_factory/mechanism_math/formula_specific.py` 中：

```python
mechanism_contract = (mechanism_analysis or {}).get("mechanism_math_contract") if isinstance(mechanism_analysis, dict) else {}
if isinstance(mechanism_contract, dict):
    fields.update(str(item).lower() for item in mechanism_contract.get("observable_inputs") or [] if str(item).strip())
```

这会导致：

- 公式文本/IR/required inputs 没有 `volume`；
- 错误机制合同写了 `observable_inputs=["volume"]`；
- `features["has_volume"]` 被置为 `true`；
- price-volume contradiction 不再 BLOCK。

这是方向性错误。公式字段必须来自公式本身或 canonical spec，不得由机制分析反向补写。

### P1-2: profit payer 推导仍是泛化占位

当前生成内容包含：

```python
payer = "the counterparty implied by the economic hypothesis"
why_pay = "they pay only if constrained behavior, delayed information diffusion, risk transfer, or liquidity demand creates a repeatable state"
```

validator 只检查非空字符串，所以 generic placeholder 可以 PASS。这个不满足用户核心要求：

> 数学机制应根据经济假设选择合适建模。DCF、stochastic process 等可以是 baseline，再根据经济机制 mutation，用积分、微分、条件期望、状态转移等推导 who is profit payer and how do they generate profit for me。若 metrics 不支持假设，应能观察并 mutate formula。

## 设计要求

### A. 公式字段必须 formula-only

修改 `formula_features()`：

- `fields` 只能来自：
  - `canonical_spec.required_inputs`
  - `canonical_spec.required_fields`
  - `canonical_spec.observable_inputs`，如果该字段属于 canonical formula/spec，而不是 mechanism analysis
  - `formula_ir` field nodes
  - `formula_text` token parsing
- 不得从 `mechanism_analysis.mechanism_math_contract.observable_inputs` 更新 `fields`。
- 可以新增独立字段，例如：
  - `mechanism_observable_inputs`
  - `formula_missing_mechanism_inputs`
  - `mechanism_inputs_not_in_formula`
- `has_volume`、`has_high_low`、`has_sign_or_threshold`、`has_250_window` 等公式特征必须只基于 formula/spec fields/operators/constants。

### B. 机制 observable inputs 要单独一致性检查

在 `validate_mechanism_formula_consistency()` 中新增检查：

- 如果 `mechanism_math_contract.observable_inputs` 包含 `volume/amount/turnover`，但 formula-derived fields 不含这些字段，并且 mechanism text 声称 price-volume / volume liquidity / volume covariance 等，则 BLOCK：
  - `BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION`
- 如果 mechanism contract observable inputs 包含公式没有的字段，记录到 consistency result：
  - `mechanism_inputs_not_in_formula`
- 不要因为 mechanism contract 多写字段就让 contradiction PASS。

### C. profit payer derivation 必须具体化

`build_formula_specific_derivation()` 需要根据 economic text、selected baseline model、formula components 生成更具体的 payer 推导。

最小可接受结构：

```json
"profit_payer_derivation": {
  "payer_or_counterparty": "具体 payer class，例如 late trend chasers / liquidity demanders / valuation-risk sellers / information-disadvantaged traders",
  "why_they_pay": "该 payer 为什么在这个经济机制下付出预期收益",
  "mechanism_generating_profit": "用所选数学模型解释 profit transfer：状态变量、条件期望、冲击衰减、估值误差修正等",
  "expected_payoff_expression_or_argument": "具体条件期望/状态转移/估值方程/收益表达式，不允许只有 E[r|F] 泛化模板",
  "economic_hypothesis_source": "引用 broad return source + second layer hypothesis 的摘要",
  "math_model_link": "说明 selected baseline model 如何刻画 payer 行为",
  "formula_state_link": "说明公式组件如何估计该 payer 造成的 latent state"
}
```

可以用启发式生成，但必须是机制相关，不允许纯占位。示例规则：

- `valuation_identity`: payer 可以是 earnings/growth/discount-rate risk 承担方或估值错误修正的对手方；表达式应围绕 `P_t = E[FCF]/(r-g)`、earnings revision、discount-rate shock。
- `state_space`: payer 可以是 information-disadvantaged / delayed updater / attention-constrained trader；表达式应围绕 latent information state、Bayesian update、signal extraction。
- `transient_impact`: payer 可以是 liquidity demander / forced rebalancer / order-imbalance taker；表达式应围绕 `I_{t+1}=rho I_t + eta`、temporary impact decay。
- `copula_rank_dependence`: payer 可以是 crowding/rank-dependence mispricer；表达式应围绕 conditional rank dependence / copula state，不得只说 rank。
- `jump_threshold`: payer 可以是 threshold/bucket migration trader；表达式应围绕 stopping-time / discontinuous state boundary / turnover cost。
- `stochastic_process`: payer 可以是 trend/reversal state counterparty；表达式应围绕 drift/reversal/jump/vol state conditional return。
- `other`: 必须写明 under-specified，并应触发 `needs_human_review` 或 validation warning/BLOCK，不能假装完整。

### D. validator 必须拒绝 generic payer placeholder

在 `validate_formula_specific_derivation()` 中增加 blocker。

建议 token：

- `BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC`

必须 BLOCK 以下模式：

- `payer_or_counterparty` 等于或包含：
  - `the counterparty implied by the economic hypothesis`
  - `counterparty implied`
  - `generic payer`
  - `market participants`
  - `investors`
  - `traders`
  - `they pay only if`
- `why_they_pay` 只是枚举四大来源，不绑定具体 model/formula component。
- `mechanism_generating_profit` 只说 “formula estimates the state” 而没有 model-specific mechanism。
- `expected_payoff_expression_or_argument` 只写泛化 `E[r_{t+1:t+h} | F_t, estimated_state_t]`，没有状态变量或 baseline model 结构。
- 缺少 `economic_hypothesis_source` / `math_model_link` / `formula_state_link`。

注意：validator 不需要读取 hidden chain-of-thought，只验证公开 artifact 的研究结论和推导摘要。

## 修改文件

必须修改：

- `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/formula_specific.py`
- `/Users/humphrey/projects/factor-factory/scripts/run_step6_intelligence_smoke.py`

可能需要修改：

- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_step6.py`
  - 只有当新增 failure code 需要更明确地穿透到 Step6 validator 输出时才改。
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/SKILL.md`
  - 如果合同文字需要同步。
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/SKILL.md`
  - 仅当 Ultimate 文档也需要说明 payer derivation blocker。

不要修改：

- Step3B / Step4 性能代码。
- `run_factorforge_ultimate_loop.py`，除非现有 smoke 证明必要。
- promotion gate / official library 写入逻辑。
- clean data / search worker。

## 必须新增 smoke cases

在 `/Users/humphrey/projects/factor-factory/scripts/run_step6_intelligence_smoke.py` 的 `run_formula_specific_mechanism_smoke()` 中新增至少两个负例。

### Case 1: polluted mechanism observable input 不能绕过 no-volume contradiction

构造：

```python
spec = alpha019_like_spec()
bad_mechanism = {
    'return_source': 'behavioral_microstructure',
    'factor_family': 'reversal',
    'mechanism_hypothesis': 'Generic price-volume dependence and volume liquidity explain this signal.',
    'mechanism_fit': 'weak',
    'mechanism_math_contract': {
        'observable_inputs': ['close', 'returns', 'volume'],
    },
    'mechanism_math_summary': {
        'model_family': 'price_volume_microstructure',
    },
}
derivation = build_formula_specific_derivation(spec, bad_mechanism, {})
consistency = validate_mechanism_formula_consistency(spec, bad_mechanism, derivation)
```

期望：

- `consistency.status == "BLOCK"`
- failure code 包含 `BLOCK_MECHANISM_FORMULA_FIELD_CONTRADICTION`
- `consistency.features.has_volume == false`
- result 中记录 `mechanism_inputs_not_in_formula` 包含 `volume`

Smoke case 名建议：

- `alpha019_polluted_mechanism_observable_volume_still_blocks`

### Case 2: generic payer placeholder 必须 BLOCK

构造：

```python
good_mechanism = {... existing alpha019 valid mechanism ...}
derivation = build_formula_specific_derivation(spec, good_mechanism, {})
derivation['profit_payer_derivation'] = {
    'payer_or_counterparty': 'the counterparty implied by the economic hypothesis',
    'why_they_pay': 'they pay only if constrained behavior, delayed information diffusion, risk transfer, or liquidity demand creates a repeatable state',
    'mechanism_generating_profit': 'expected payoff arises only if the formula estimates the state that causes that payer behavior or constraint',
    'expected_payoff_expression_or_argument': 'E[r_{t+1:t+h} | F_t, estimated_state_t] must be monotone in the declared direction after costs.',
}
failures = validate_formula_specific_derivation(derivation, spec, good_mechanism)
```

期望：

- failures 包含 `BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC`

Smoke case 名建议：

- `generic_profit_payer_derivation_blocks`

### Case 3: model-specific payer derivation PASS

保留或新增正例：

- valuation economic hypothesis -> `valuation_identity`，payer derivation 包含 cash-flow / earnings / discount-rate 等 model-specific 词。
- information hypothesis -> `state_space`，payer derivation 包含 delayed updater / information-disadvantaged / latent information state 等。
- market-structure hypothesis -> `transient_impact`，payer derivation 包含 liquidity demander / transient impact / order imbalance decay 等。

期望：

- `validate_formula_specific_derivation()` 无 failures。
- `selected_model_family` 与 expected family 一致。
- `profit_payer_derivation` 非 generic。

## 验证命令

在 `/Users/humphrey/projects/factor-factory` 执行：

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/formula_specific.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  scripts/run_step6_intelligence_smoke.py
```

```bash
python3 scripts/run_step6_intelligence_smoke.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_phase_o_p1_formula_payer_fix
```

期望：

- `verdict=ACCEPT`
- `alpha019_polluted_mechanism_observable_volume_still_blocks.ok=true`
- `generic_profit_payer_derivation_blocks.ok=true`
- canonical pollution false

回归验证：

```bash
python3 scripts/run_step6_intelligence_acceptance.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_acceptance_phase_o_p1_formula_payer_fix
```

期望：

- stdout 包含 `STEP6_INTELLIGENCE_ACCEPTED`

```bash
python3 scripts/run_step6_council_primary_smoke.py \
  --fresh \
  --root /tmp/factorforge_step6_council_primary_phase_o_p1_formula_payer_fix
```

期望：

- `verdict=ACCEPT`
- canonical pollution false

```bash
python3 scripts/run_factorforge_ultimate_loop_smoke.py \
  --fresh \
  --root /tmp/factorforge_ultimate_loop_phase_o_p1_formula_payer_fix
```

期望：

- `verdict=ACCEPT`
- canonical pollution false

如果修改了 Step6 / Ultimate skill 文档，需要同步 installed skill：

```bash
rsync -a --delete /Users/humphrey/projects/factor-factory/skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/
rsync -a --delete /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
diff -qr -x __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
diff -qr -x __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
```

## 验收标准

Reviewer 必须确认：

- P0/P1/P2 均为 none。
- Alpha019-like no-volume formula 即使 mechanism contract 污染 `observable_inputs=volume` 仍然 BLOCK。
- `formula_features().has_volume` 不再受 mechanism analysis 污染。
- generic payer placeholder 被 validator BLOCK。
- valid model-specific payer derivation PASS。
- Step6 intelligence smoke ACCEPT。
- Step6 intelligence acceptance 仍 `STEP6_INTELLIGENCE_ACCEPTED`。
- Council-primary / loop smoke 不回归。
- installed Step6 / Ultimate skill diff clean，如有文档修改。
- 未跑真实因子、未处理 clean data、未执行 search worker、未写 official promotion、未改 Step3B/Step4 性能路径。

## 给 coder 的最终交付格式

请按以下格式回复：

```text
已完成 Phase O P1 formula-field / payer-derivation 窄修。

修改文件：
- ...

核心修复：
- formula_features 不再从 mechanism_math_contract.observable_inputs 推导 formula fields。
- polluted observable_inputs=volume 不能绕过 Alpha019-like no-volume contradiction。
- profit_payer_derivation generic placeholder 现在 BLOCK。
- valid model-specific payer derivation PASS。

新增 smoke：
- alpha019_polluted_mechanism_observable_volume_still_blocks: PASS
- generic_profit_payer_derivation_blocks: PASS
- model_specific_profit_payer_derivation_pass: PASS

验证：
- py_compile PASS
- Step6 intelligence smoke ACCEPT: <summary path>
- Step6 intelligence acceptance: STEP6_INTELLIGENCE_ACCEPTED
- Step6 council primary smoke ACCEPT
- ultimate loop smoke ACCEPT
- installed diff clean: <if applicable>

确认未做：
- 未跑真实因子
- 未处理 clean data
- 未执行 search worker
- 未写 official promotion
- 未改 Step3B/Step4 性能路径
```
