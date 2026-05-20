# Factor Forge Ultimate 反馈：Alpha026 Derivation Engine 修复后真实复测评估

Date: 2026-05-20

Audience: Factor Forge Architect

## 1. 背景与结论

本反馈基于 Alpha026 在 derivation-engine 修复后的 fresh production-path retest，不是基于旧 artifact 复述。测试目标是确认：

1. 主 agent 是否能在 Step1/2/6 机制层自行给出公式特异性的 economic hypothesis 和 math mechanism，而不是抄公式或套 price-volume 模板；
2. Revision Council 是否能根据 Step1/2 hypothesis、Step4/5 metrics、Step6 preliminary analysis 推导下一轮数学机制和可执行公式；
3. Council 是否不再作为提前 reject engine，在未到 `max_loops` 且没有 terminal authority 时跳过 loop；
4. 失败的 child revision 是否被记录为 branch-level falsification，并成为下一轮 Council 的 prior revision memory。

结论：

- 主方向已经达标：这次 Alpha026 路径体现了 `economic hypothesis -> stochastic-process math model -> observable estimator -> metric signature -> falsification -> next model-term mutation` 的闭环。
- Council 行为已经从 verdict/reject engine 明显转向 derivation engine：先做 estimator repair，再做 model-term repair，最后在两条 branch 失败后写 branch falsification，而不是直接 reject 整个因子。
- 仍有两个 artifact hardening 缺口：机制 memo 的顶层字段仍有 `null`，核心内容落在 `mechanism_qa`；Council appendix 仍出现 `Research question: missing` 和 `Limiting Cases: missing`。这说明推理内容已基本达标，但结构化输出合同还不够硬。

## 2. 本次真实测试对象

Root report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101_DERIVATION_ENGINE_RETEST_20260520_093527
```

Parent formula:

```text
multiply(-1, max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
```

Child 1 report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101_DERI__6600276b56__LOOP01__ARCHIMEDES_ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL
```

Child 1 formula:

```text
multiply(-1, max(correlation(ts_rank(volume, 10), ts_rank(high, 10), 10), 5))
```

Child 2 report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL
```

Child 2 formula:

```text
multiply(-1, max(correlation(ts_rank(delta(volume, 1), 10), ts_rank(high, 10), 10), 5))
```

关键 proof / evidence：

- `objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_DERIVATION_ENGINE_RETEST_20260520_093527.json`
- `objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_DERI__6600276b56__LOOP01__ARCHIMEDES_ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/runtime_context/ultimate_loop_report__ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL/branch_falsification__ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`

## 3. 用户标准复述

用户需要的不是“Council 更宽松”，也不是“Council 多试几个参数”。标准是：

1. 主 agent 必须先形成公式特异性的 economic hypothesis 和 math hypothesis；
2. math hypothesis 不是抄公式，而是根据经济机制选择合适的数学模型，例如 stochastic process、dimensional analysis、cross-variation、wavelet / Fourier、projection、copula 等；
3. Council 必须根据 Step1/2 的经济与数学假设，结合 Step4/5 metrics 和 Step6 preliminary analysis，推导下一步研究方向；
4. 在保持经济假设大方向不变的前提下，Council 可以调整数学模型、latent state、observable estimator 和公式表达式；
5. Council 可以 falsify 一个 revision branch，但不能在未到 `max_loops` 且缺少 terminal authority 时直接 reject 整个因子；
6. 每一轮 revision 必须回答：谁付钱、为什么付钱、公式估计什么状态、数学模型中哪个项被证伪、下一轮如何修改模型项、预期 metrics signature 是什么。

## 4. Alpha026 原始 Economic Hypothesis

Alpha026 使用 `volume` 与 `high`，核心交互是：

```text
correlation(ts_rank(volume, 5), ts_rank(high, 5), 5)
```

主 agent memo 对该公式的经济解释是：

- `ts_rank(volume, 5)` 估计局部参与压力或成交拥挤；
- `ts_rank(high, 5)` 估计局部上沿价格压力；
- 两者的 rolling correlation 估计高成交与高价位是否同步；
- `max(..., 3)` 惩罚最近几天任何一次同步拥挤 spike；
- `multiply(-1, ...)` 将“高成交高价格同步拥挤弱或缺失”转成高分。

因此原始 economic hypothesis 是：

```text
当高成交与高价位同步上升时，股票可能处在 attention chase / urgent demand / volume-confirmed trend participation 的拥挤状态。
这些资金为了立刻参与，承担冲击成本和不利选择。
Alpha026 通过买入该同步拥挤状态较弱的股票，尝试收割拥挤追价后的冲击衰减或不良补偿。
```

Return source 分类不是纯 risk premium，也不是纯 information advantage，而是：

```text
mixed = market-structure harvesting + avoidance of volume-conditioned transient impact
```

Payer / counterparty:

```text
attention chasers,
volume-confirmation trend allocators,
urgent liquidity takers,
crowded short-horizon demand accounts
```

这部分达标：它没有泛泛说 price-volume microstructure，而是把公式的字段、算子、符号和谁付钱连在一起。

## 5. Alpha026 原始 Math Mechanism

主 agent 选择的数学模型是 stochastic-process mutation。基础模型为：

```text
dX_i,t = mu_i,t dt + sigma_i,t dB_i,t
```

根据 Alpha026 的成交量与高价位字段，扩展为：

```text
dX_i,t = mu_i,t dt + sigma_i(V_i,t, Z_i,t) dB_i,t + kappa_i(V_i,t, Z_i,t) dt
```

其中：

- `X_i,t` 是价格或 log price 状态；
- `V_i,t` 是成交/参与压力；
- `Z_i,t` 是局部价格压力、拥挤状态或 attention state；
- `sigma(V,Z)` 表示 volume-conditioned volatility；
- `kappa(V,Z)` 表示 transient impact drift；
- rolling dependence `C_i,t` 是对成交压力和上沿价格压力同步性的 observable estimator。

公式映射为：

```text
Rv_i,t = ts_rank(volume_i,t, w)
Rh_i,t = ts_rank(high_i,t, w)
C_i,t  = corr_w(Rv_i,t, Rh_i,t)
S_i,t  = -max_m(C_i,t)
```

这解决了两个关键问题：

1. 量纲问题：`volume` 和 `high` 原本不可直接比较，`ts_rank` 后变成 dimensionless local state；
2. 公式含义问题：`correlation` 不是泛化“价量相关”，而是估计 `V` 与上沿价格压力之间的同步状态。

预期 metric signature：

- rank IC 为正，说明该状态能排序未来收益；
- high-score long side 应该为正，不能只靠低分组亏损；
- 如果短窗口噪声是主要问题，平滑后 turnover 应显著下降；
- 如果经济机制真实且估计器改进有效，cost-adjusted annual return 应转正或显著改善；
- drawdown / recovery 应改善，否则状态可能只是排序噪声或风险暴露。

## 6. 第一轮 Evidence 与 Council 推导

Parent metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.03455956977816864` |
| `rank_ic_ir` | `0.4846884777155941` |
| `pearson_ic_mean` | `0.02240498337104332` |
| `turnover_mean` | `0.3828962315861602` |
| `long_side_annual_return` | `0.06498433177605042` |
| `long_side_sharpe` | `0.28647006148393844` |
| `long_side_max_drawdown` | `-0.4186107972380336` |
| `long_side_recovery_days` | `1634` |
| `cost_adjusted_annual_return` | `-0.22435219101674517` |

Council 不是直接 reject，而是做了正确的第一层诊断：

```text
信号有排序信息和正的 gross long-side return，
但 5/5/3 窗口导致状态估计过快，
turnover 太高，成本吞噬收益。
```

因此 Council 推导出 estimator repair：

```text
5/5/3 -> 10/10/5
```

即：

```text
multiply(-1, max(correlation(ts_rank(volume, 10), ts_rank(high, 10), 10), 5))
```

数学解释：

- 保持同一 latent state `C_i,t = corr(Rv, Rh)`；
- 不改变经济假设和符号；
- 只降低 estimator variance 和 score churn；
- 用更慢的 state observer 测试“是否只是交易成本问题”。

这一步达标：它是从 metrics 反推 estimator 问题，再映射到可执行公式。

## 7. 第二轮 Evidence 与 Council 推导

10/10/5 child metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.03400677683707856` |
| `rank_ic_ir` | `0.3941113829277116` |
| `pearson_ic_mean` | `0.02207713749375702` |
| `turnover_mean` | `0.2088525997038902` |
| `long_side_annual_return` | `0.05884078360227068` |
| `long_side_sharpe` | `0.26155233294073926` |
| `long_side_max_drawdown` | `-0.4493285975395489` |
| `long_side_recovery_days` | `1634` |
| `cost_adjusted_annual_return` | `-0.09897881848118267` |

结果说明：

- 平滑有效：turnover 从 `0.3829` 降到 `0.2089`；
- 信息保留：rank IC 从 `0.03456` 仅降到 `0.03401`；
- 但经济性仍不成立：成本后年化仍为 `-9.90%`；
- 风险没有修复：max drawdown 从 `-41.86%` 恶化到 `-44.93%`。

Council 正确将 `10/10/5` 标记为 branch-level falsification，并通过 `prior_revision_memory` 禁止重复该 derivation rule / formula hash。

第二轮推导没有继续窗口搜索，而是切换数学模型项：

```text
从 volume level V_i,t
切换到 participation shock dV_i,t
```

对应 stochastic process 解释：

```text
dX_i,t = mu_i,t dt + sigma_i(V_i,t,Z_i,t)dB_i,t + kappa_i(V_i,t,Z_i,t)dt
```

上一轮只修了 `C_i,t` 的 observation kernel；这一轮改观测对象，从 `V_i,t` 改成 `dV_i,t`，测试急迫参与是否更体现在成交量变化而不是成交量水平。

选出的 child formula:

```text
multiply(-1, max(correlation(ts_rank(delta(volume, 1), 10), ts_rank(high, 10), 10), 5))
```

这一步也达标：它不是重复调参，而是一个 distinct model-term repair。

## 8. 第三轮 Evidence 与 Council 行为

Participation-shock child metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.01692929602922012` |
| `rank_ic_ir` | `0.3314513148715463` |
| `pearson_ic_mean` | `0.014704172842115788` |
| `turnover_mean` | `0.260907663146836` |
| `long_side_annual_return` | `-0.011541273043821222` |
| `long_side_sharpe` | `-0.051387690154343545` |
| `long_side_max_drawdown` | `-0.5776574764613938` |
| `long_side_recovery_days` | `2961` |
| `cost_adjusted_annual_return` | `-0.20869627535493326` |

结果说明：

- `dV` participation shock 不是修复项；
- rank IC 明显减弱；
- high-score long annual return 转负；
- drawdown 大幅恶化；
- cost-adjusted annual return 仍深负。

第三轮 Council 五个 real-agent 结果都没有给新公式，而是形成 branch-stop / no-derived-revision-with-proof：

- smoothing level-dependence branch 已失败；
- participation-shock branch 已失败；
- 不应重复窗口或相近 hash；
- 如果继续，必须推导 distinct mathematical object，不能在当前分支内硬试。

最关键的是：系统没有因此直接 reject 整个因子。

最终 loop 状态：

```text
final_outcome = awaiting_next_derivation
stop_reason   = revision_branch_falsified_next_derivation_required
```

Terminal bridge 被明确拦截：

```text
BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS
```

Branch falsification artifact 写入：

```text
objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL/branch_falsification__ALPHA026_CANONICAL_FORMULA_20160101_DE__05afbc42c6__LOOP01__ALPHA026_PARTICIPATION_SHOCK_DEPENDENCE_10_10_5_SINGLE_TRIAL.json
```

这正是用户要求的行为：Council 可以证明某条 branch 没有继续价值，但不能在 `max_loops` 前越权杀死整个 factor research。

## 9. 已达标部分

### 9.1 主 Agent 机制建模

本次 root memo 已经回答：

- broad return source；
- payer / counterparty；
- why they pay；
- formula state estimator；
- stochastic-process baseline and mutation；
- expected metric signature；
- falsification gates。

尤其是它没有把 Alpha026 泛化成“price-volume microstructure”模板，而是围绕 `high` 与 `volume` 的短窗口 rank dependence 解释经济与数学机制。

### 9.2 Council 推导链条

Council 形成了较完整链条：

```text
parent evidence:
  positive IC + positive gross long side + high turnover + deeply negative net

first derivation:
  estimator variance / churn failure
  -> 10/10/5 smoother state observer

child evidence:
  turnover improved + IC preserved + net still negative + drawdown worse

second derivation:
  level-dependence observer falsified
  -> change model term from V level to dV participation shock

second child evidence:
  IC weakens + high-score payoff negative + drawdown much worse

third Council:
  branch-level falsification
  -> no repeated formula hash / no repeated derivation rule
  -> awaiting next distinct math mechanism, not terminal reject
```

这符合“像推导数学模型一样修订 Step3 公式”的方向。

### 9.3 Loop Governance

本次验证显示：

- `revision_council.effective_mode=agentic_dispatch_manifest`；
- `deterministic_scaffold_used=false`；
- 5 个 real-agent Council result 均通过 validator；
- completed Council 之后由主 agent 写 synthesis，再 approval bridge，再 materialize child；
- child formula hash 与 parent 不同；
- failed child revision 写入 prior revision memory；
- premature terminal reject 被 BLOCK；
- 未写 official promotion；
- 未处理 clean data；
- 未执行 search worker。

## 10. 仍需修复 / 硬化的问题

### 10.1 Main-agent memo 顶层结构仍不够硬

Root memo 中部分顶层字段仍为 `null`：

```json
{
  "math_model_selection": null,
  "payer": null,
  "formula_state_estimator": null,
  "expected_metric_signature": null,
  "falsification_tests": null
}
```

虽然这些内容实际存在于 `mechanism_qa` 里，但这会造成下游读取不稳定。建议 validator 要求关键字段在顶层也必须结构化存在，不能只藏在自由文本 QA。

建议硬合同：

```text
main_agent_mechanism_memo must contain non-null:
  economic_hypothesis.return_source_class
  economic_hypothesis.payer_or_counterparty
  economic_hypothesis.why_they_pay
  math_model_selection.model_family
  math_model_selection.baseline_model
  math_model_selection.model_mutation
  formula_state_estimator.latent_state
  formula_state_estimator.observable_mapping
  expected_metric_signature
  falsification_tests
```

### 10.2 Council appendix 仍有占位缺口

Appendix 中多处出现：

```text
Research question: missing
Limiting Cases: missing
```

这说明 result validator 接受了核心推导，但没有要求 agent 或 appendix builder 填完整研究问题与 limiting-case analysis。

建议硬合同：

- `research_question` 不得 missing；
- `limiting_cases` 至少包含 2 个：
  - one positive limiting case：什么情况下机制应该最强；
  - one negative limiting case：什么情况下机制必然失效；
- 对 stochastic process 角色，limiting cases 应包括：
  - `V` 与 `high` 独立；
  - `V` 上升但价格压力不持续；
  - `dV` shock 只代表噪声交易而非 urgent demand；
  - 高成交高价同步代表强趋势而非拥挤反转时，符号会失败。

### 10.3 `prior_revision_memory.metric_delta.turnover` 为 null

Packet 的 `prior_revision_memory` 中，turnover delta 是：

```json
"turnover": {
  "child": null,
  "delta": null,
  "parent": null
}
```

但 Alpha026 的关键失败机制恰恰与 turnover/cost 有关。真实 metrics 中 turnover 是存在的：

```text
parent turnover_mean = 0.3828962315861602
smooth turnover_mean = 0.2088525997038902
shock turnover_mean  = 0.260907663146836
```

建议修复 `prior_revision_memory` 的 metric extraction，至少包含：

- `turnover_mean`
- `long_side_turnover_mean_daily`
- `trading_cogs_annual` if available
- `cost_adjusted_annual_return`
- `long_side_max_drawdown`
- `long_side_recovery_days`

否则 Council 会在文字中正确讨论 cost/turnover，但结构化 memory 缺少核心数值。

### 10.4 Branch falsification 后的 next derivation 入口需要更明确

当前状态正确停在：

```text
awaiting_next_derivation
```

但下一步如何继续还不够产品化。建议新增明确 artifact：

```text
objects/research_iteration_master/revision_council/<report_id>/next_derivation_questionnaire__<report_id>.json/md
```

内容应要求主 agent 回答：

1. 已证伪的 model components 是什么；
2. 禁止重复的 formula hashes 和 derivation rules 是什么；
3. 是否仍保留原 economic hypothesis；
4. 如果保留，下一条 distinct math mechanism 是什么；
5. 如果不保留，是否有足够 terminal authority；
6. 是否需要 human override 才能 early stop。

这样 `awaiting_next_derivation` 就不是一个半自动停点，而是可继续的研究合同。

### 10.5 Terminal authority 应区分 branch / instance / family

建议正式枚举：

```text
terminal_scope:
  revision_branch_only
  factor_instance
  mechanism_family
```

并要求不同级别的 proof：

- `revision_branch_only`：一个 child formula 或 derivation rule 被证伪；
- `factor_instance`：已达到 max loops，或所有合法 distinct math mechanisms 均失败，或用户批准 stop；
- `mechanism_family`：经济机制本身被证伪，需要证明不只是当前表达式失败。

本次 Alpha026 正确落在：

```text
terminal_scope = revision_branch_only
stop_authority = advisory_only
next_required_action = derive_distinct_math_mechanism
```

这个行为应保持。

## 11. 对 Alpha026 当前研究判断

Alpha026 的经济假设不是无意义的。它描述的是：

```text
高成交与高价位同步带来的拥挤/冲击/急迫参与状态。
```

数学机制也不是随便拼公式，确实可以解释为：

```text
volume-conditioned stochastic process 中的同步压力状态估计器。
```

但当前 evidence 对可交易性不友好：

1. 原始版本有 IC 和 gross long side，但交易成本完全吞噬；
2. 平滑版本证明了短窗口噪声存在，但不能修复净收益和 drawdown；
3. participation-shock 版本证明 `dV` 模型项更差；
4. 第三轮 Council 没有给出当前分支内可信的新公式。

因此当前应记录为：

```text
Alpha026 current branch falsified.
Alpha026 not promotable.
Alpha026 not yet formally factor-level rejected by automatic Council before max_loops.
Further continuation requires a distinct math mechanism, not another nearby window or same dependence kernel.
```

## 12. 推荐架构任务

建议给 coder 的任务可以拆成五项：

1. Hard-fill main-agent memo top-level fields
   - 将 `mechanism_qa` 中的核心答案结构化提升到顶层；
   - validator BLOCK 顶层关键字段为 null 的 memo。

2. Harden Council result / appendix completeness
   - `research_question` 和 `limiting_cases` 不得 missing；
   - 每个 agent result 必须至少写一个 positive limiting case 和一个 negative limiting case。

3. Fix `prior_revision_memory` metric extraction
   - turnover / cost / drawdown / recovery 必须结构化进入 memory；
   - 对 cost-driven failures，缺 turnover 应 BLOCK 或 WARN upgraded to BLOCK。

4. Add `awaiting_next_derivation` continuation contract
   - 生成 `next_derivation_questionnaire`;
   - 主 agent 写 `next_derivation_memo`;
   - validator 确认没有重复 falsified formula hash / derivation rule；
   - 合格后才允许下一轮 synthesis 或 terminal authority request。

5. Formalize terminal authority ladder
   - `revision_branch_only` 默认不能结束整个 factor；
   - `factor_instance` reject 需要 max loops、human approval 或完整 no-derived-revision proof；
   - `mechanism_family` reject 需要更高证明标准。

## 13. 最终判断

这轮修复后的 Factor Forge Ultimate / Step6 Council 已经达到用户想要的主要研究行为：

- 主 agent 能做公式特异性经济与数学机制建模；
- Council 能结合 metrics 推导 estimator repair 和 model-term repair；
- failed revision 能进入 prior memory；
- Council 不再在未到 max loops 时越权 terminal reject；
- wrapper / validator / branch falsification artifacts 保持可审计。

但还不应宣称机制层 artifact 已完全成熟。下一步要硬化的不是“让 Council 更聪明”这种泛泛目标，而是把已经出现的好推理强制结构化：

```text
no null top-level mechanism fields
no missing research question
no missing limiting cases
no missing turnover/cost memory
no ambiguous awaiting_next_derivation state
no branch-level falsification upgraded to factor-level reject without terminal authority
```

如果上述合同补齐，Factor Forge Ultimate 的机制研究闭环会从“真实行为基本达标”进入“artifact contract 也达标”的状态。
