# Factor Forge Research Quality Gate 完善计划

日期：2026-06-23
适用范围：Factor Forge Ultimate / Researcher / Step6 / Council / Research Brain

## 背景

`TURNRATE_VOL_TREND_PENALTY_14_30` 暴露的问题不是 Factor Forge 没有价值，而是现有 skill 和 validator 更擅长保证工程闭环：

- artifacts 齐全；
- Step6 / Council validator 通过；
- official library 未误写入；
- window evidence 被补齐；
- 工作区和知识库边界安全。

这些是必要条件，但不能证明研究员真的完成了研究。LLM 会优化最硬的门槛；如果最硬门槛是文件齐全和流程 PASS，agent 就会倾向于把研究写成合格文档，而不是把经济机制、数学对象、payer、状态过程和证伪实验拆开验证。

## 根因判断

### 1. 隐性奖励函数偏向流程完成

当前系统的强约束主要检查“有没有文件”和“validator 是否 PASS”。这会鼓励 agent 追求流程闭环，而不是研究闭环。强化学习 agent 不能自动解决这个问题；如果 reward 仍然是流程通过，RL 只会更会刷流程。

### 2. 研究字段允许 narrative 冒充 validation

`economic_hypothesis`、`math_discipline_review`、`stochastic process`、`Council derivation` 等字段已经存在，但很多约束仍停留在“必须写”。只要没有强制 claim level 和证据链接，agent 就能用看似专业的机制叙述替代实证拆解。

### 3. Council 独立性和研究深度没有被分层

`local_mock`、deterministic scaffold、main-agent sequential result、independent subagent result、human reviewed result 对研究质量的证明力不同。当前 artifact 层能区分一部分 producer，但 skill 层没有强制 agent 不得把低深度 scaffold 结果包装成正式独立研究。

### 4. 数学工具没有自动变成实验义务

当 agent 声称使用 stochastic process、Dirac-style induction、barrier/hitting、occupation measure、projection 等工具时，必须同时承担相应实验义务。否则数学语言只是 framing，不是 validation。

### 5. 证据层级混用

window-contract evidence、robustness evidence、diagnostic evidence、promotion-gate evidence 经常混在同一段结论里。agent 容易拿补充证据支撑更强结论，尤其在想尽快收口时。

## 目标行为

未来 Factor Forge 研究员不能只说“机制合理”或“Council 通过”。它必须回答：

1. 这个因子试图让谁支付收益，payer/receiver 是谁？
2. 公式里的每个核心组件保留了什么信息、删除了什么信息、别名化了什么信息？
3. 机制 claim 达到了哪个等级，证据是什么？
4. 如果使用 stochastic process，状态空间、条件漂移、状态 persistence、barrier/tail 风险是否被验证？
5. 如果使用 Dirac-style induction，atomic state、invariant、estimator law、limiting cases、falsification design 是否形成可复用 law？
6. 当前证据是 promotion gate、robustness、diagnostic、window contract，还是 exploratory？
7. Council 输出是 placeholder、main-agent sequential、independent agent，还是 human reviewed？
8. 这个结论如何改变下一个研究员的行为？

## Claim 等级制度

所有 serious Step6 / Council / researcher memo 必须声明 `mechanism_claim_level`，禁止二元的 `mechanism_present=true`。

等级从低到高：

```text
none
narrative_only
math_framed
metric_consistent
component_validated
stochastic_validated
payer_validated
```

定义：

- `none`：没有可信机制。
- `narrative_only`：只有经济故事或经验判断，没有公式结构和实证拆解。
- `math_framed`：选了数学对象或工具，但没有对应实验。
- `metric_consistent`：总指标与机制方向一致，但没有组件拆解。
- `component_validated`：至少有 component ablation、joint-state bucket、liquidity/regime split 或 parent-vs-revision information delta。
- `stochastic_validated`：有状态空间、条件收益分布、transition persistence 或 barrier/tail risk 证据。
- `payer_validated`：payer/receiver 假说有可证伪代理变量、分桶或反事实证据支持。

正式研究结论最多只能声称达到已证明等级。`math_framed` 不能写成 `validated`，`metric_consistent` 不能支撑 official promotion。

## Research Quality Gate

新增一等公民概念：`research_quality_gate`。它独立于 artifact validator。

最低要求：

- `economic_payer_hypothesis`：明确 payer/receiver，或写明无法识别；
- `math_object_contract`：公式对应的随机对象、状态变量、target statistic 和信息集；
- `claim_level`：按等级制度声明；
- `evidence_tier_map`：每个证据 artifact 的用途层级；
- `component_validation_plan_or_result`：组件拆解、joint bucket、regime/liquidity split、parent-vs-revision delta 中至少一类；
- `falsification_design`：能推翻该机制的实验；
- `overclaim_guard`：哪些话不能说，哪些结论只是 hypothesis。

推荐后续代码任务：

```bash
python3 skills/factor-forge-step6/scripts/validate_research_quality.py --report-id <report_id>
```

在 validator 未实现前，skill 必须要求 agent 在 researcher memo、Step6 memo 或 Council synthesis 中手工写出上述 contract。

## Stochastic Process Contract

任何使用 stochastic process、drift、barrier、hitting probability、survival state、state transition 等语言的研究，必须声明：

- `stochastic_process_status`: `not_used` / `framing_only` / `validated`
- `state_space`
- `conditional_return_distribution`
- `transition_matrix_or_persistence_proxy`
- `barrier_or_tail_risk_test`
- `revision_state_information_delta`

如果上述证据缺失，只能标记 `framing_only`，不能称为 stochastic validated。

## Dirac Induction Memo

当 agent 声称完成 Dirac-style induction、symbolic law discovery、可迁移机制 law，必须写：

```text
objects/research_iteration_master/dirac_induction_memo__<report_id>.json
objects/research_iteration_master/dirac_induction_memo__<report_id>.md
```

必填字段：

- `atomic_state`
- `invariant`
- `estimator_law`
- `deleted_information_audit`
- `limiting_cases`，至少 3 个；
- `falsification_design`
- `reuse_boundary`
- `overclaim_guard`

没有这个 memo，只能说“有机制假说”或“有数学 framing”，不能说完成了 Dirac-style induction。

## Council 质量分层

Council output 必须声明 `research_depth`：

```text
contract_placeholder_result
deterministic_scaffold
main_agent_sequential_result
independent_agent_result
human_reviewed_result
```

正式 research-quality claim 只能由 `independent_agent_result` 或 `human_reviewed_result` 支撑。`main_agent_sequential_result` 可以作为研究材料，但必须标记为非独立。`contract_placeholder_result` 和 `deterministic_scaffold` 只能证明结构，不证明机制。

每个 Council role 除了 proposal，还必须输出：

- `what_information_is_preserved`
- `what_information_is_deleted`
- `what_metric_would_change_if_the_claim_is_true`
- `what_observation_would_kill_the_claim`
- `dirac_atomic_law_candidate`

## Evidence Tier Map

每个 evidence artifact 必须标注用途：

```text
promotion_gate_evidence
robustness_evidence
diagnostic_evidence
window_contract_evidence
exploratory_evidence
```

规则：

- promotion 只能使用 `promotion_gate_evidence`；
- `window_contract_evidence` 只能证明窗口覆盖，不证明机制；
- `diagnostic_evidence` 可以解释失败，不能独立支持 adoption；
- `exploratory_evidence` 只能生成下一步假说；
- supplemental evidence 不能覆盖原 Step4 promotion evidence。

## 强化学习 agent 的位置

强化学习 agent 应该放在第三阶段，而不是第一阶段：

1. 先定义 research-quality reward：claim level、component validation、stochastic validation、payer validation、overclaim guard。
2. 再让 agent 在这些 contract 下选择 ablation、bucket、regime split、revision、kill branch。
3. 最后才能用 RL 或 bandit-style policy 学习“哪类 revision 在什么机制下更值得试”。

没有 research quality gate 的 RL 会放大流程主义。正确用法是让 RL 优化研究质量，不是优化文件闭环。

## Rollout 任务书

### 第一阶段：skill 立即强化

更新以下 skill：

- `skills/factor-forge-ultimate/SKILL.md`
- `skills/factor-forge-researcher/SKILL.md`
- `skills/factor-forge-step6/SKILL.md`
- `skills/factor-forge-step6-researcher/SKILL.md`
- `skills/factor-forge-research-brain/SKILL.md`

要求：

- 新增 claim 等级；
- 新增 Research Quality Gate；
- 新增 stochastic process contract；
- 新增 Dirac induction memo；
- 新增 evidence tier map；
- 明确 Council research depth；
- 明确 RL 只是策略学习器，不是研究质量替代品。

### 第二阶段：validator 实现

新增：

- `skills/factor-forge-step6/scripts/validate_research_quality.py`
- `scripts/run_factorforge_research_quality_smoke.py`

覆盖负例：

- stochastic 只有语言 framing 却标记 validated；
- claim level 低却写成 promotion-ready；
- Council scaffold 被当成 independent；
- evidence tier 混用；
- Dirac claim 缺 memo；
- revision 没写 deleted information audit。

### 第三阶段：wrapper 集成

`run_factorforge_ultimate.py` 在 formal Step6 / Council / loop closeout 后调用 research quality gate。失败时允许保留工程 artifacts，但最终状态必须是 `research_quality_blocked`，不能写成 completed research。

### 第四阶段：历史案例回填

优先回填：

- `TURNRATE_VOL_TREND_PENALTY_14_30`
- LCR retained chip
- Moneyflow V18/V19/V21
- CPV occupation/location
- Alpha101 复杂组合反例

每个回填案例至少写一份 `dirac_induction_memo` 或明确标记 `research_quality_level=metric_consistent_only`。

## 验收标准

短期验收：

- skill 中明确禁止“文档完整即研究完成”；
- serious research 必须声明 mechanism claim level；
- stochastic / Dirac / Council / evidence tier 都有明确 contract；
- installed skill 与 repo skill 同步。

中期验收：

- `validate_research_quality.py` 能阻断反馈书中的 TURNRATE 类问题；
- Ultimate wrapper 能把工程 PASS 但研究质量不足的 run 标为 `research_quality_blocked`；
- 新研究 thread 的 final answer 必须区分 `engineering closed` 与 `research-quality accepted`。

最终目标：

让 Factor Forge 的默认行为从“跑完并写文档”变成“提出、拆解、验证、证伪、沉淀一个研究假说”。只有这样，多 agent、Council 或未来 RL policy 才会提高研究质量，而不是更高效地完成形式流程。
