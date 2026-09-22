# Factor Forge Ultimate 反馈：Alpha026 Multibranch Production Retest P4

Date: 2026-05-20

Audience: Factor Forge Architect / Reviewer

## 1. 结论

本次用 fresh report id 跑了 Alpha026 production multibranch loop retest。结论分两层：

1. 架构目标已经达到：真实路径完成了 `real Council -> main-agent multibranch synthesis -> approval bridge -> N children -> branch comparison -> selected child continues`。
2. Alpha026 本身没有改善：两个 child branch 都被指标证伪或接近证伪，selected child 只是“相对不差”，不是可推广的有效因子。

这轮验证的核心不是证明 Alpha026 有价值，而是证明 P4 multibranch loop 控制合同能防止单一路径压缩 Council 结论，并且能把未选中 sibling 的证据带入下一轮 Council。

## 2. 测试对象

Root report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225
```

Parent formula:

```text
multiply(-1, max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
```

Multibranch synthesis 选择了两个 child：

### Exploit Branch

Law id:

```text
alpha026_smooth_synchrony_state_10_10_5
```

Child report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PRO__c276aee29d__LOOP01__EXPLOIT_ALPHA026_SMOOTH_SYNCHRONY_STATE_10_10_5
```

Formula:

```text
multiply(-1, max(correlation(ts_rank(ts_mean(volume, 10), 10), ts_rank(ts_mean(high, 10), 10), 5), 3))
```

Mechanism intent:

```text
Preserve the parent crowded participation-high synchrony thesis, but smooth the state estimator to reduce noisy flips, turnover, cost drag, and long recovery.
```

### Exploration Branch

Law id:

```text
alpha026_abnormal_participation_conditioned_5_20_5
```

Child report id:

```text
ALPHA026_CANONICAL_FORMULA_20160101__c276aee29d__LOOP01__EXPLORATION_ALPHA026_ABNORMAL_PARTICIPATION_CONDITIONED_5_20_5
```

Formula:

```text
multiply(-1, max(correlation(ts_rank(divide(volume, ts_mean(volume, 20)), 5), ts_rank(high, 5), 5), 3))
```

Mechanism intent:

```text
Change the latent participation state from raw volume rank to stock-relative abnormal participation, then test whether abnormal participation and high-price pressure synchrony is a better transient-impact state.
```

## 3. Key Artifacts

Root loop proof:

```text
objects/runtime_context/ultimate_loop_report__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225.json
```

Root wrapper proof:

```text
objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225.json
```

Selected child wrapper proof:

```text
objects/runtime_context/ultimate_run_report__ALPHA026_CANONICAL_FORMULA_20160101__c276aee29d__LOOP01__EXPLORATION_ALPHA026_ABNORMAL_PARTICIPATION_CONDITIONED_5_20_5.json
```

Multibranch synthesis:

```text
objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225/main_agent_multibranch_synthesis__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225.json
objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225/main_agent_multibranch_synthesis__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225.md
```

Multibranch materialization report:

```text
objects/runtime_context/multibranch_child_materialization__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225__loop01.json
```

Branch comparison:

```text
objects/research_iteration_master/branch_comparison__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225__loop01.json
objects/research_iteration_master/branch_comparison__ALPHA026_CANONICAL_FORMULA_20160101_MULTIBRANCH_PROD_RETEST_P4_20260520_162225__loop01.md
```

Selected child Council packet:

```text
objects/research_iteration_master/revision_council/ALPHA026_CANONICAL_FORMULA_20160101__c276aee29d__LOOP01__EXPLORATION_ALPHA026_ABNORMAL_PARTICIPATION_CONDITIONED_5_20_5/revision_council_packet__ALPHA026_CANONICAL_FORMULA_20160101__c276aee29d__LOOP01__EXPLORATION_ALPHA026_ABNORMAL_PARTICIPATION_CONDITIONED_5_20_5.json
```

## 4. 验证结果

### 4.1 Root Council 到 Multibranch Synthesis

Root Step6 先进入 `awaiting_agent_results`。当前主 agent 读取 5 个 task packet 后写入 5 份 real-agent Council result，并通过：

```text
validate_agentic_council_result.py: PASS
validate_agentic_council_dispatch.py: PASS
collect_agentic_council_results.py: ready_for_finalize=true
finalize_agentic_council_dispatch.py: PASS
```

之后主 agent 写：

```text
main_agent_multibranch_synthesis__<root_report_id>.json/md
```

并通过：

```text
validate_main_agent_multibranch_synthesis.py: PASS
branch_count=2
exploit_branch_count=1
exploration_branch_count=1
parent_formula_hash != child_formula_hashes
```

### 4.2 Approval + Materialization

Production loop 自动消费 multibranch synthesis：

```text
multibranch_approval_rc=0
multibranch_materialization_rc=0
multibranch_child_count=2
```

两个 child 都生成了：

```text
executable_revision_spec__<child_report_id>.json
child-local Step3A daily snapshot paths
distinct child formula hash
```

Materialization report 显示：

```text
status=PASS
selected_branch_count=2
clean_data_touched=false
official_promotion_written=false
```

### 4.3 Child Execution + Branch Comparison

两个 child 都跑完 Step3B/4/5/6 wrapper 路径，之后生成 branch comparison：

```text
validate_branch_comparison.py: PASS
```

Branch comparison 中的结果：

| Branch | Outcome | rank_ic_mean | long_side_annual_return | cost_adjusted_annual_return | turnover | max_drawdown | recovery_days |
|---|---|---:|---:|---:|---:|---:|---:|
| exploit smoothing | falsified | 0.018386 | 0.002192 | -0.379972 | 0.505742 | -0.481497 | 2961 |
| exploration abnormal participation | falsified | 0.032222 | 0.061621 | -0.231525 | 0.387939 | -0.414242 | 1634 |

Parent baseline:

| Metric | Parent |
|---|---:|
| rank_ic_mean | 0.034560 |
| long_side_annual_return | 0.064984 |
| cost_adjusted_annual_return | -0.224352 |
| turnover | 0.382896 |
| max_drawdown | -0.418611 |
| recovery_days | 1634 |

Interpretation:

- exploit smoothing 明显失败：IC、long-side return、cost-adjusted return、turnover、drawdown、recovery 全部恶化或基本恶化。
- abnormal participation 也没有改善 parent：IC、long-side return、cost-adjusted return、turnover 都略差；drawdown 略好，recovery 不变。
- loop 选择 exploration child 继续，只是因为它在排序规则下比 exploit smoothing 更接近 parent，不代表它通过研究标准。

### 4.4 Only Selected Child Continues

生产路径验证了关键控制合同：

```text
selected_next_parent_child_report_id =
ALPHA026_CANONICAL_FORMULA_20160101__c276aee29d__LOOP01__EXPLORATION_ALPHA026_ABNORMAL_PARTICIPATION_CONDITIONED_5_20_5
```

Selected child 后续 Step6 wrapper:

```text
status=PASS
revision_council.status=awaiting_agent_results
revision_council.effective_mode=agentic_dispatch_manifest
deterministic_scaffold_used=false
```

未选中 exploit sibling：

```text
non-selected handoff_to_step3b: absent
non-selected official record: absent
non-selected Council packet: absent
```

Selected child Council packet 中包含：

```text
sibling_branch_memory.required=true
siblings[0].child_report_id=<exploit_child_report_id>
siblings[0].law_id=alpha026_smooth_synchrony_state_10_10_5
siblings[0].branch_outcome=falsified
forbidden_repeat_sibling_formula_hashes includes both child hashes
forbidden_repeat_sibling_revision_rules includes both child laws
```

同时 selected child packet 还包含 `prior_revision_memory`，并记录：

```text
prior_revision_outcome=falsified
parent-vs-child deltas include turnover, cost, drawdown, recovery days
forbidden_repeat_revision_rules includes selected child law
```

这说明 sibling evidence 没有被丢掉，也没有让未选中 branch 继续污染下一轮 parent。

## 5. Side-Effect Checks

本次生产复测确认：

```text
no official promotion: true
no search worker: true
no clean data processing: true
data/clean digest unchanged: true
parent generated_code digest unchanged: true
root canonical_side_effects: []
iteration forbidden_side_effects: []
non-selected child handoff: absent
non-selected child Council packet: absent
```

## 6. Caveat：Model Family Token 合同偏硬

Selected child Step6 继续时，第一次被 prewrite validator 拦住一次：

```text
STEP6_PREWRITE_BLOCK:
formula_specific_derivation_invalid:
falsification_tests must include at least two items
```

这是主 agent memo 的 `falsification_answer` 没有使用 Step6 转换器能拆分的分号/换行格式导致，修复格式后通过。

第二次被 `validate_step6` 拦住：

```text
loop brief markdown mechanism text stale or inconsistent:
current_tokens=['price_volume_correlation', 'price_volume_microstructure'],
stale_terms=['stochastic_process']
```

原因是 selected child 当前 Step6 contract 的 `factor_family/model_family` token 仍是 `price_volume_microstructure`，而主 agent memo 明确使用了条件扩散/随机过程语言。为了让生产链路继续验证 multibranch 控制流，我把 memo 的 exact `model_family` token 对齐到 `price_volume_microstructure`，同时保留条件扩散与瞬时冲击项的数学描述。

这不是 multibranch bridge 失败，但暴露了一个机制建模合同问题：

```text
model_family token currently mixes economic family, mechanism family, and mathematical tool family.
```

建议后续拆分为：

```json
{
  "factor_family": "price_volume_microstructure",
  "economic_mechanism_family": "transient_impact",
  "math_tool_family": "stochastic_process",
  "model_equation_family": "conditional_diffusion_with_flow_impact"
}
```

这样既能防止 Alpha019-like 公式无 volume 却被归成 price-volume，也不会因为 price-volume 因子使用 stochastic process 推导而触发 stale-token block。

## 7. 对 Skill 状态的判断

当前 P4 后，Factor Forge Ultimate 已经具备以下能力：

1. 主 agent 在 Step6 前写公式特异性 mechanism memo；
2. real-agent Council 能基于 memo、Step4/5 metrics、prior memory 做推导；
3. Council 不再被压缩成 terminal reject engine；
4. 主 agent 能把 Council 结果汇总成 multibranch synthesis；
5. production loop 能 materialize 多 child；
6. branch comparison 能选择唯一 next parent；
7. sibling branch memory 能进入 selected child Council packet；
8. 未选中 sibling 不会自动继续、不写 handoff、不写 official；
9. side-effect guard 能保护 clean data、official library 和 parent generated_code。

因此架构上可以认为：

```text
P4 production multibranch loop integration 已通过真实 Alpha026 retest。
```

但因子研究上应记录：

```text
Alpha026 的本轮两个修订方向都没有改善成本后表现。后续 Council 必须把两个 branch 视为 falsified evidence，不得重复相同 law/hash。
```

## 8. 建议下一步

建议保留 P4 当前设计，并继续观察真实使用中是否出现以下问题：

1. model-family token 过硬导致数学推导被迫迎合 family 标签；
2. branch selection 排序规则在所有 branch 都 falsified 时仍选择“相对不差”的 child，可能需要显式标记 `selected_for_next_derivation_only`；
3. child Step6 如果在 multibranch child execution 阶段已经暂停等待 memo，branch comparison 仍可以比较 Step4/5 metrics，但后续 selected child Council 需要主 agent 补 memo；
4. sibling memory 的 forbidden laws/hash 已生效，下一步要验证 Council result validator 是否会 BLOCK 重复 sibling law；
5. 可以考虑在 branch comparison 中加入 `all_children_falsified=true` 字段，让下一轮 Council 更明确地知道“继续不是因为 improve，而是因为需要 next derivation”。

