# Factor Forge Ultimate 问题反馈：Revision Council 不应是提前 Reject 引擎，而应是数学机制推导引擎

Date: 2026-05-20

Audience: Factor Forge Architect

Related case:

- `ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818`
- child: `ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL`

Key proof paths:

- `objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818.json`
- `objects/runtime_context/ultimate_loop_report__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818.json`
- `objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/runtime_context/ultimate_loop_report__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/research_iteration_master/main_agent_mechanism_memo__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818.json`
- `objects/research_iteration_master/main_agent_mechanism_memo__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818/revision_council_summary__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818.json`
- `objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818/main_agent_council_synthesis__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818.json`
- `objects/research_iteration_master/executable_revision_spec__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL/revision_council_summary__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`
- `objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL/terminal_council_rejection__ALPHA026_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_1818__LOOP01__ALPHA026_SMOOTH_DEPENDENCE_10_10_5_SINGLE_TRIAL.json`

## Summary

Alpha026 暴露了一个比单个因子更重要的架构问题：当前 Revision Council 在真实路径中已经能够读取 Step1/2 机制、Step4/5 metrics、Step6 preliminary analysis，并产出 agentic results；但是 Council 的实际行为仍偏向“根据 metrics 判定继续或 reject”，而不是“根据 economic hypothesis 推导更合适的 math mechanism，再把 math mechanism 翻译成下一轮 Step3 factor expression”。

这不是希望 Council 更宽松。恰恰相反，Council 应该更严格，但严格对象应从 `verdict` 转移到 `derivation`：

```text
不是：
  child 修订失败 -> Council 一致 terminal reject -> loop 提前结束

而是：
  child 修订失败 -> 标记该 revision law falsified
                 -> 回到 economic hypothesis 和 math mechanism
                 -> 推导新的数学模型或状态变量
                 -> 翻译为新的可执行 factor expression
                 -> 进入下一轮 Step3B/4/5/6
                 -> 最多 10 loop，除非真实 BLOCK
```

当前 Alpha026 只执行了一个 child loop：`5/5/3 -> 10/10/5`。这个 child 平滑分支失败后，Council 通过 terminal reject bridge 关闭了研究。按用户真实意图，这属于 **premature terminal rejection**。正确状态应是：

```text
10/10/5 smoothing branch falsified
Alpha026 production factor not promotable yet
Alpha026 research loop incomplete
Council must derive a distinct next math mechanism or BLOCK with proof
```

## User Requirement

用户对 Council 的核心要求不是“给出更多调参建议”，而是：

1. 从 Step1/2 的 `economic_hypothesis` 和 `math_hypothesis` 出发；
2. 结合 Step4/5 metrics 和 Step6 preliminary analysis；
3. 深入细节修订 economic hypothesis 和 math mechanism；
4. 在保持 economic hypothesis 大方向不变的前提下，重新选择或修改数学模型；
5. 像推导物理/数学公式一样推导 latent state、observable estimator、target functional、metric signature；
6. 将新 math mechanism 映射成 Step3 可执行表达式；
7. 用 Step3B/4/5/6 验证；
8. 在 max loops 之前，不允许 Council 因一个 revision branch 失败而自行结束整个因子研究。

用户提出的 `dimensional analysis`、`stochastic calculus`、`wavelet analysis`、`stochastic process` 等不是固定工具清单，而是希望 Council 具备数学建模能力。Council 必须根据因子公式、可观测字段、经济机制和 evidence 选择合适工具，也可以说明某些工具不适合；但不能只做 metrics verdict。

## Alpha026 Trigger Case

Alpha026 parent formula:

```text
multiply(-1, max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
```

Main-agent mechanism memo 将其解释为：

```text
S_i,t = -max_{j=0..2} corr_5(ts_rank_5(volume), ts_rank_5(high))_{i,t-j}
```

大方向 economic hypothesis：

```text
high volume 与 high price 同步时，可能代表 crowded attention / transient impact / liquidity-demand pressure。
因子取负号，即买入近期没有强烈高量高价同步拥挤的股票。
```

Parent Step4 metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.03455956977816864` |
| `rank_ic_ir` | `0.4846884777155941` |
| `turnover_mean` | `0.3828962315861602` |
| `long_side_annual_return` | `0.06498433177605042` |
| `long_side_sharpe` | `0.28647006148393844` |
| `long_side_max_drawdown` | `-0.4186107972380336` |
| `cost_adjusted_annual_return` | `-0.22435219101674517` |

Parent Council correctly识别了一个局部问题：信号有 IC，但 turnover/cost 太高。因此它提出一个平滑 child：

```text
multiply(-1, max(correlation(ts_rank(volume, 10), ts_rank(high, 10), 10), 5))
```

Child Step4 metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.03400677683707856` |
| `rank_ic_ir` | `0.3941113829277116` |
| `turnover_mean` | `0.2088525997038902` |
| `long_side_annual_return` | `0.05884078360227068` |
| `long_side_sharpe` | `0.26155233294073926` |
| `long_side_max_drawdown` | `-0.4493285975395489` |
| `cost_adjusted_annual_return` | `-0.09897881848118267` |

Child 结论很清楚：

- `10/10/5` 平滑方向有一定效果，turnover 从 `0.3829` 降到 `0.2089`；
- rank IC 基本保留；
- 但 cost-adjusted annual return 仍为负；
- long-side drawdown 更差；
- 说明 “window smoothing repair” 被证伪。

问题在下一步：Council 直接 terminal reject，而不是回到 math mechanism 继续推导下一条 distinct revision law。

## Why Current Behavior Is Wrong

当前系统将以下三种概念混在了一起：

1. `revision_branch_reject`
   - 某一个 child formula 或 revision law 被证伪；
   - 应禁止重复该 formula hash / derivation rule；
   - 但不代表整个 factor instance 或 mechanism family 结束。

2. `factor_instance_reject`
   - 当前 factor 在给定研究预算下不值得继续；
   - 需要证明没有 material improvement path，或已经达到 max-loops / human-approved stop。

3. `mechanism_family_reject`
   - 整个经济机制方向被证伪；
   - 要求更高，需要说明为什么所有合理数学模型变体都不成立或不可合法实现。

Alpha026 child 只证明了：

```text
revision_branch_reject: 10/10/5 smoothing law failed.
```

它没有证明：

```text
factor_instance_reject: Alpha026 所有合理 math mechanism revision 都失败。
mechanism_family_reject: price-volume dependence / volume-conditioned process 没有研究价值。
```

因此 Council 的 terminal reject bridge 在未达 max-loops 时不应自动关闭整个研究。

## Desired Council Role: Derivation Engine

Revision Council 应从 verdict engine 改为 derivation engine。每轮 Council 结果必须先回答：

```text
What mathematical model explains the economic hypothesis?
Which model term did the formula estimate?
Which model term did the metrics falsify?
How should the mathematical model mutate?
How does the new model imply a new observable estimator?
How is that estimator translated into a Step3 executable expression?
What metric signature would confirm/falsify this new mechanism?
```

Council 可以 reject 一个工具、一个模型、一个 branch，但不能没有推导就 reject 整个研究。

## Example: Alpha026 Stochastic Process Direction

以下是用户举的例子，用来说明希望 Council 具备的推导能力。请不要将修复硬编码为这个例子；它只是代表目标研究深度。

Alpha026 同时包含 `volume` 和 `high`，可假设价格过程含 volume-conditioned term。基础模型可以从：

```text
dX_t = mu_t dt + sigma_t dB_t
```

扩展为：

```text
dX_t = mu_t dt + sigma(V_t, Z_t) dB_t
```

或：

```text
dX_t = mu_t dt + sigma_0 dB^P_t + sigma_v g(V_t) dB^V_t + impact(V_t, Z_t) dt
```

其中：

- `X_t` 是价格或 log price；
- `V_t` 是成交量状态；
- `Z_t` 是拥挤、流动性需求或 attention state；
- `corr(ts_rank(volume), ts_rank(high))` 可能是在估计 `V_t` 与 upward price pressure 的相关结构；
- 高正相关可能代表高量高价拥挤；
- 负相关或低相关可能代表没有追高拥挤或存在供给吸收。

Council 应进一步推导：

```text
对 f(X_t, V_t, Z_t) 做 Ito:

df = f_X dX + f_V dV + 1/2 f_XX d<X> + f_XV d<X,V> + 1/2 f_VV d<V>
```

这会迫使 Council 明确：

- 原公式估计的是 drift、diffusion、cross-variation、volume-conditioned volatility，还是 transient impact？
- `correlation(ts_rank(volume), ts_rank(high))` 是否只是粗糙 proxy？
- 如果 child smoothing 保留 IC 但 net 仍负，失败的是 estimator variance、payoff magnitude、drawdown regime、还是状态变量定义？
- 下一轮应修改哪个数学项？

可能导出的下一类机制不是简单窗口平滑，而是：

1. `volume-conditioned volatility`
   - 将高量高价同步解释为条件波动率上升；
   - 新表达式可能需要把 correlation 与 volatility / amplitude 分离。

2. `price-volume quadratic covariation`
   - 关注 `d<X,V>` 或 rank-based co-variation；
   - 新表达式可能测试相关性强度和符号的非对称性，而不是 `max(corr)`。

3. `transient impact drift`
   - 将 volume shock 放入 drift / impact term；
   - 新表达式可能需要区分 volume-driven upward pressure 和 subsequent reversal。

4. `horizon separation`
   - 用 wavelet / spectral / multi-scale reasoning 区分短期噪声与中期状态；
   - 新表达式可能同时保留短窗冲击项和长窗状态项，而不是单纯把窗口拉长。

5. `state persistence / stopping-time`
   - 关注拥挤状态首次出现、持续、消退；
   - 新表达式可能从 `max` 改为 persistence / decay estimator。

这些方向都必须由 Council 根据公式和 evidence 推导，而不是由 Python 模板固定枚举。

## Required Architecture Changes

### 1. Add terminal scope and forbid premature factor-level reject

Council recommendation must include:

```json
{
  "terminal_scope": "revision_branch_only | factor_instance | mechanism_family",
  "stop_authority": "advisory_only | block_with_proof | max_loop_cap | human_override",
  "loop_index": 1,
  "max_loops": 10
}
```

Before `max_loops` is reached, Council may not close `factor_instance` unless one of these is true:

- validator BLOCK proves implementation/evaluation is impossible or illegal;
- Council produces `BLOCK_NO_DERIVED_REVISION_WITH_PROOF`;
- user explicitly approves early stop;
- formula/data/operator constraints make all proposed legal revisions unimplementable and this is validated.

Otherwise, a failed child must be recorded as:

```text
revision_branch_only rejected
next derivation required
```

### 2. Replace automatic terminal reject with branch falsification by default

Current rule:

```text
completed real-agent Council unanimously recommends terminal rejection
-> close_terminal_council_rejection.py
-> decision=reject
```

Required rule:

```text
completed real-agent Council unanimously recommends terminal rejection
and loop_index < max_loops
-> require terminal_scope proof
-> if no proof: write branch_falsification artifact, not factor reject
-> require next math-mechanism derivation or BLOCK_NO_DERIVED_REVISION_WITH_PROOF
```

`close_terminal_council_rejection.py` should be guarded by:

```text
loop_index >= max_loops
OR human_override=true
OR validated_no_derived_revision=true
OR evidence_block=true
```

### 3. Require Council to produce math-mechanism revision before reject

Each Council agent result should include:

```json
{
  "economic_hypothesis_review": {
    "preserve_broad_direction": true,
    "refined_second_layer_mechanism": "...",
    "payer_or_counterparty_update": "...",
    "what_step4_metrics_changed_in_the_hypothesis": "..."
  },
  "math_mechanism_derivation": {
    "selected_tool": "stochastic_process | stochastic_calculus | dimensional_analysis | wavelet_analysis | ...",
    "rejected_tools": [
      {"tool": "...", "reason": "..."}
    ],
    "baseline_model": "...",
    "model_mutation": "...",
    "mathematical_objects": ["..."],
    "derivation_steps": ["..."],
    "derived_state_variables": ["..."],
    "observable_estimators": ["..."],
    "expected_metric_signature": ["..."],
    "falsification_tests": ["..."]
  },
  "model_to_formula_translation": {
    "candidate_formula": "...",
    "formula_hash_if_parseable": "...",
    "operator_support_status": "parseable | blocked_operator | needs_direct_code | needs_hybrid",
    "mapping_from_model_terms_to_formula_components": ["..."],
    "information_set_legality": "legal | illegal | uncertain"
  }
}
```

If `candidate_formula` is absent, the result must say whether this is:

```text
research_hold
operator_block
no_derived_revision_with_proof
```

It must not silently become factor reject.

### 4. Add main-agent orchestration duty after Council

The main agent should not simply aggregate Council verdicts. It must act as orchestra:

1. compare Council derivations, not just recommendations;
2. select one mathematically strongest revision law;
3. explain why it preserves or refines the broad economic hypothesis;
4. translate the selected math mechanism into child formula / direct code / hybrid plan;
5. write `main_agent_council_synthesis`;
6. approve bridge only after formula mapping and validator pass.

If all Council roles recommend stop but do not provide enough proof for `BLOCK_NO_DERIVED_REVISION_WITH_PROOF`, the main agent should not close the factor. It should write:

```text
awaiting_human_math_direction
or
BLOCK_COUNCIL_NO_VALID_DERIVATION
```

### 5. Separate parameter repair from model repair

Alpha026 parent Council selected `10/10/5` smoothing. That was a parameter/window repair, not a math-mechanism revision.

The contract should require every proposed revision to declare:

```json
{
  "revision_kind": "parameter_repair | estimator_repair | model_term_repair | model_family_shift | economic_hypothesis_refinement",
  "same_model_family": true,
  "new_mathematical_object_added": false,
  "why_this_is_not_cosmetic": "..."
}
```

After a `parameter_repair` fails, the next loop must not propose another nearby parameter repair unless Council explicitly derives why the first parameter choice was wrong. The expected next step is usually `model_term_repair` or `estimator_repair`.

### 6. Make `prior_revision_memory` a generative constraint, not just a stop constraint

Current `prior_revision_memory` correctly records:

- parent/child formula hash;
- derivation rule;
- parent-vs-child metric delta;
- `prior_revision_outcome=falsified`;
- forbidden repeat rule/hash.

But in Alpha026 it functioned as “do not repeat, therefore reject.” It should instead function as:

```text
do not repeat falsified rule
derive a distinct mathematical mechanism
explain what metric failure says about the model
```

Add required fields:

```json
{
  "prior_revision_model_diagnosis": {
    "which_model_component_failed": "...",
    "which_metric_falsified_it": "...",
    "what_model_change_is_implied": "..."
  },
  "next_revision_must_change": [
    "state_definition",
    "observable_estimator",
    "model_term",
    "horizon_decomposition"
  ]
}
```

### 7. Add validation tokens

Proposed hard BLOCK tokens:

```text
BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION
BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS
BLOCK_COUNCIL_NO_MODEL_TO_FORMULA_MAPPING
BLOCK_COUNCIL_NO_TOOL_SELECTION_RATIONALE
BLOCK_COUNCIL_REPEATS_FALSIFIED_REVISION_RULE
BLOCK_COUNCIL_PARAMETER_REPAIR_AFTER_PARAMETER_FAILURE_WITHOUT_MODEL_DIAGNOSIS
BLOCK_NO_DERIVED_REVISION_WITH_PROOF
```

Warnings:

```text
WARN_COUNCIL_BRANCH_REJECT_NOT_FACTOR_REJECT
WARN_COUNCIL_DERIVATION_NOT_EXECUTABLE_YET
WARN_COUNCIL_TOOL_REJECTED_AS_UNJUSTIFIED
```

### 8. Fix loop outcome semantics

`run_factorforge_ultimate_loop.py` should distinguish:

```text
branch_rejected
factor_rejected
mechanism_family_rejected
awaiting_next_derivation
awaiting_human_math_direction
max_loops_reached
blocked
```

It should not collapse `branch_rejected` into `rejected`.

Expected loop progression:

```text
parent Step6 iterate
-> Council derives child law
-> child Step3B/4/5/6
-> child Step6 says prior law falsified
-> Council must derive next distinct law
-> main agent synthesis
-> next child
...
-> stop only at promote / max loops / validated no-derived-revision / user override / true BLOCK
```

## Acceptance Tests

### Smoke: terminal reject before max loops should block

Fixture:

- report has `loop_index=1`, `max_loops=10`;
- Council collection has 5 valid real-agent results;
- all recommend `terminal_reject`;
- no result contains `BLOCK_NO_DERIVED_REVISION_WITH_PROOF`;
- no human override;
- no validated evidence BLOCK.

Expected:

```text
close_terminal_council_rejection.py returns non-zero
token = BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS
no decision=reject writeback
handoff_to_step3b absent
official absent
data/clean unchanged
generated_code unchanged
```

### Smoke: branch falsification artifact

Same fixture as above.

Expected artifact:

```text
objects/research_iteration_master/revision_council/<report_id>/branch_falsification__<report_id>.json
```

Required fields:

```json
{
  "falsified_revision_rule": "...",
  "falsified_formula_hash": "...",
  "terminal_scope": "revision_branch_only",
  "next_required_action": "derive_distinct_math_mechanism"
}
```

### Smoke: no derivation means no Council result

Agent result with recommendation only:

```json
{
  "revision_or_kill_recommendation": "reject"
}
```

Expected:

```text
validate_agentic_council_result.py fails
token = BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION
```

### Smoke: parameter repair after failed parameter repair requires model diagnosis

Prior revision memory:

```text
revision_kind = parameter_repair
prior_revision_outcome = falsified
```

New Council result proposes another window-only parameter change.

Expected:

```text
BLOCK_COUNCIL_PARAMETER_REPAIR_AFTER_PARAMETER_FAILURE_WITHOUT_MODEL_DIAGNOSIS
```

unless it includes a concrete model diagnosis explaining why the prior parameter repair failed and why the new parameter law is not a repeat.

### Real-case regression: Alpha026 should not end after one child

Use existing Alpha026 child state or a fresh report id.

Expected:

```text
10/10/5 child is marked falsified
Council cannot terminal-reject the factor before max loops
Council must produce a next distinct math-mechanism derivation or BLOCK_NO_DERIVED_REVISION_WITH_PROOF
root loop does not report final_outcome=rejected merely because child smoothing failed
```

## Important Non-Goals

Do not hardcode Alpha026-specific stochastic calculus.

Do not force every factor into stochastic calculus. For some factors, the correct tool may be:

- dimensional analysis;
- jump process;
- stopping-time reasoning;
- copula / dependence structure;
- robust statistics;
- tail distribution;
- Fourier / wavelet / horizon decomposition;
- projection / residualization geometry;
- information theory;
- market microstructure queue/impact model;
- or a simple discrete-state model.

The contract should force **tool selection and derivation quality**, not a specific tool.

Do not let Python generate the derivation. Python may:

- extract formula facts;
- validate fields/operators;
- validate schema;
- check parseability;
- compare formula hashes;
- enforce no-writeback boundaries.

The current main agent and Council agents must do the free-form mathematical reasoning.

## Proposed Skill Text Changes

Add to `factor-forge-ultimate/SKILL.md` and `factor-forge-step6/SKILL.md`:

```text
Revision Council is a derivation engine, not a verdict engine. Its primary job
is to refine the economic hypothesis and derive a better mathematical mechanism
from Step1/2 hypotheses plus Step4/5/6 evidence. A Council may reject a branch,
tool, formula, or derivation rule, but before max_loops it must not terminally
reject the factor unless it produces validated proof that no legal, executable,
formula-mappable mathematical revision remains, or the user explicitly approves
early termination.

After a child revision is falsified, Council must diagnose which mathematical
model component failed and derive a distinct next mechanism or return
BLOCK_NO_DERIVED_REVISION_WITH_PROOF. Repeating a falsified rule/hash is
forbidden, but failure of one branch is not sufficient to reject the factor
instance.

Every Council result must include a public mathematical derivation record:
economic hypothesis review, selected and rejected mathematical tools, baseline
model, model mutation, derivation steps, derived state variables, observable
estimator mapping, model-to-formula translation, expected metric signature,
falsification tests, and kill criteria. A recommendation without derivation is
invalid.
```

## Proposed Implementation Surface

Likely files:

- `skills/factor-forge-step6/scripts/validate_agentic_council_result.py`
- `skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py`
- `skills/factor-forge-step6/scripts/build_revision_council_packet.py`
- `skills/factor-forge-step6/scripts/merge_revision_council.py`
- `skills/factor-forge-step6/scripts/build_council_derivation_appendix.py`
- `skills/factor-forge-step6/scripts/close_terminal_council_rejection.py`
- `skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py`
- `scripts/run_factorforge_ultimate_loop.py`
- `factor_factory/ultimate_loop/state.py`
- Step6 / Ultimate installed skill docs

Keep all changes contract-first with `/tmp` smoke coverage before real-case rerun.

## Bottom Line

Alpha026 shows that the current system is now good enough to run real agentic Council, but the control objective is still wrong.

The desired objective is not:

```text
find a quick reason to reject weak factors
```

The desired objective is:

```text
use Council to derive better mathematical mechanisms from economic hypotheses,
translate them into executable factor expressions, and only reject after
bounded, non-repeating, mathematically justified revision loops are exhausted
or truly blocked.
```

Until this is fixed, Alpha026 should be treated as:

```text
branch 10/10/5 falsified
full factor research incomplete
premature Council terminal reject exposed an orchestration/contract gap
```

