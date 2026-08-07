# Factor Forge Research Conjecture Protocol v1

## 1. 目的

本协议把 Factor Forge 从“填写完整研究 artifact”升级为“可持续搜索、可证伪、
可重定向、可机器审计的金融研究系统”。

它借鉴四类方法，但不直接复制：

1. OpenAI Cycle Double Cover 工作流中的动态多路线、早期独立、路线登记、
   缺口阻断、对抗审查和 root-agent 重定向；
2. AlphaProof 的 formalize-first、verifier-first 和 verified-feedback；
3. FunSearch 的 executable candidate、自动 evaluator、候选数据库、多样性和迭代；
4. 数学家与大模型协作中的短问题拆解、快速淘汰死路、fresh-context critic 和
   人类/独立复核。

金融研究没有 Lean kernel。收益证据低信噪比、非平稳，并受成本与容量影响，
所以协议只把可以精确验证的部分形式化；经济机制必须使用分层证据，不得伪装成定理。

## 2. 不能照搬数学证明的部分

1. 不得假设一定存在 alpha。每个研究必须同时保留 `preferred`、`null` 和至少一个
   `alternative` hypothesis。
2. 不得用单次 IC、单窗口回测或多数 Council 意见作为“证明”。
3. 不得把 OOS 反复用于搜索奖励；OOS 在搜索期间必须 sealed。
4. 不得把 stochastic-process 语言本身当验证。只有状态、转移、条件分布和
   tail/barrier 证据齐备时，才能使用 `stochastic_validated`。
5. 不得把 payer 故事当验证。只有可观测 payer/receiver proxy 与区分性测试通过后，
   才能使用 `payer_validated`。
6. 强化学习不得直接以 IC 或回测收益为奖励。先建立可信 verifier 和研究轨迹，
   后续 RL 只能帮助选择研究路线，不能替代 sealed evidence。

## 3. 状态机

```text
FORMULATE
-> DIVERSIFY
-> ATTACK
-> DERIVE
-> TEST
-> SYNTHESIZE
-> REDIRECT
-> VERIFY
-> ACCEPT | REJECT | BLOCK
```

- `FORMULATE`：写精确研究问题、alpha claim、null、alternative、允许信息集和终止条件。
- `DIVERSIFY`：建立至少三个机制上不同的路线族。
- `ATTACK`：构造 alias、null、measurement、payer、regime 或 boundary 反例。
- `DERIVE`：明确经济博弈、数学对象、观测方程、因子估计器和收益方程。
- `TEST`：执行 proof obligations 对应的 bounded/正式实验。
- `SYNTHESIZE`：root agent 比较冲突假设和证据，不做多数表决或平均意见。
- `REDIRECT`：阻断卡住路线，仅在出现新机制、新数据或新不变量时重开。
- `VERIFY`：运行跨 artifact semantic verifier。

## 4. Artifact

所有文件必须位于当前 factor workspace：

```text
objects/research_protocol/
  research_state__<report_id>.json
  research_conjecture__<report_id>.json
  approach_registry__<report_id>.json
  proof_obligation_ledger__<report_id>.json
  counterexample_registry__<report_id>.json
  search_trial_ledger__<report_id>.json
  thresholds__<report_id>.json
  oos_release_manifest__<report_id>.json
  factor_proof_certificate__<report_id>.json
  semantic_verifier_report__<report_id>.json
```

Council root synthesis 与显式批准位于当前 workspace 的
`objects/research_iteration_master/revision_council/<report_id>/`。所有路径、
证据引用和写回都必须留在当前 factor workspace。

### 4.1 Research Conjecture

`research_conjecture` 必须包含：

- `protocol_version=factorforge_research_conjecture_protocol_v1`
- `task_statement`
- `hypotheses`
- `economic_game`
- `math_mechanism`
- `evidence_policy`
- `claim_level`
- `claim_class`

`claim_class` 在 FORMULATE 阶段冻结。它决定最终证明义务；尤其只有
`risk_premium` 才强制 Fama-MacBeth 与 quintile/decile 单调性。完整证书合同见
`docs/contracts/factorforge-factor-proof-certificate-v2.zh-CN.md`。

`task_statement` 必须定义：

- `research_question`
- `alpha_claim`
- `null_hypothesis`
- `admissible_information_set`
- `forbidden_evidence`
- `terminal_success_condition`
- `terminal_reject_condition`
- `terminal_block_condition`

### 4.2 Economic Game Contract

经济机制必须写成：

```text
participants
-> participant_constraints
-> actions
-> action_to_market_outcome
-> payoff_or_profit_transfer_equation
-> payer_candidates
-> persistence_boundary
-> capacity_boundary
-> failure_condition
```

每条 participant constraint 至少包含：

- `actor`
- `constraint`
- `why_persistent`
- `observable_proxy`
- `falsifier`

缺少可观测 proxy 时，只能是 hypothesis，不能升级为 payer validation。

### 4.3 Mathematical Mechanism Contract

最小模型是机制条件化的，不是固定的随机状态空间：

```text
mathematical object: M
mechanism equation or functional: K(M, theta)=0, V=F(M), or another justified map
market-outcome projection: Q_{t+h}=P(M, constraints, costs)
observation/estimation: Y=H(M, U)+epsilon; f=phi(Y in legal information set)
```

`H` 可以是直接可观测的恒等映射；只有选中的机制确实含有潜在状态或测量误差时，
才需要状态空间或随机观测模型。例如基本面研究可以令 `M` 为未来自由现金流、
终值和折现率，核心泛函为 DCF，市场结果为内在价值与价格之差；不需要为了满足
模板而发明扩散过程。

必须包含：

- `model_family`
- `mathematical_object`（旧 artifact 可读 `latent_state`）
- `mechanism_equation_or_functional`
- `market_outcome_equation`（旧 artifact 可读 `return_equation`）
- `observation_equation`
- `factor_estimator`
- `information_set`
- `alternative_models`
- `component_map`
- 至少三个 `limiting_cases`
- 至少两个 `expected_metric_signatures`

随机过程、状态转移、条件分布、量纲或 scaling audit 仅在所选机制使其适用时
加入；它们不是通用字段，也不是 claim level 的默认升级路线。

每个公式组件必须映射到：

- `model_term`
- `preserved_information`
- `deleted_or_aliased_information`
- `ablation_test`

如果公式只是 raw-field restatement，或数学模型无法映射回可执行 estimator，必须 BLOCK。

## 5. Dynamic Council

### 5.1 路线，而不是固定职位

Council task 必须来自 `approach_registry` 的未关闭路线。允许的路线族包括但不限于：

- `economic_game`
- `mechanism_object_measurement`（旧 artifact 的 `latent_state_measurement` 仍可读取）
- `null_alias_counterexample`
- `empirical_identification`
- `microstructure_cost`
- `regime_transition`
- `implementation_identity`
- `symbolic_law`
- `data_feasibility`

角色名只是执行标签，`route_family` 才是研究身份。不得因为换了角色名称就声称路线多样。

### 5.2 早期独立

第一轮至少两个 agent 必须：

- `favored_thesis_visible=false`
- 不读取主代理的 preferred route 或最终 revision 偏好
- 只能读取事实、公式、数据合同和已执行证据

进入 synthesis 前才允许交叉阅读。

### 5.3 Block 和 Reopen

当路线卡在以下缺口时，必须标记 `blocked`：

- `unidentified_payer`
- `unobservable_latent_state`
- `measurement_not_identifiable`
- `missing_required_data`
- `equivalent_to_original_claim`
- `implementation_not_mappable`
- `sealed_evidence_required`

blocked route 必须写 `exact_gap`、`blocked_reason`、`reopen_only_if`。只有新机制、
新不变量、新数据合同或新反例解除原缺口时才可重开。参数变化或换一种叙述不算新机制。

## 6. Proof Obligation Ledger

金融研究中的“proof obligation”是可审计义务，不是数学定理。类型包括：

- `economic_game`
- `payer`
- `measurement_validity`
- `null_alias`
- `information_set`
- `component_ablation`
- `state_transition`
- `conditional_distribution`
- `tail_or_barrier`
- `regime`
- `cost_capacity`
- `implementation_parity`

每条义务必须包含：

- `obligation_id`
- `route_id`
- `claim`
- `obligation_kind`
- `verification_method`
- `status=open|blocked|failed|passed|not_applicable`
- `evidence_refs`

`passed` 没有 evidence ref 是无效的。叙述性 Council 结论不能把义务升级为 passed。
每个 evidence ref 还必须解析到 workspace 内真实文件，且 SHA256 与
`verifier_status=PASS` 同时成立。

v1 中，能够机械关闭 promotion 所需义务的受信实现只有：

- `measurement_validity`
- `component_ablation`

二者必须使用
`factorforge_component_obligation_verifier_v1`。它从同一个冻结 OOS
cross-sectional panel 重算 full signal、ablated signal、residual signal 的逐日
rank IC，以及 full/ablated long-end return；预注册规则至少覆盖 measurement 的
full/residual IC，或 ablation 的 IC/long-end delta。验证命令：

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json>
```

semantic verifier 会重放 panel/spec/threshold，而不是相信带有正确 verifier 名称的
手写 JSON。`economic_game`、`payer`、`state_transition` 等尚无专用机械 verifier
时，可以保留 evidence 和 falsifiable conclusion，但不得将状态标成 `passed`，也
不得据此升级成 `payer_validated` 或 `stochastic_validated`。

## 7. Counterexample Registry

Council 必须主动构造反例，而不是只写 reviewer memo。反例类型包括：

- `null`
- `alias`
- `leakage`
- `measurement`
- `payer`
- `regime`
- `boundary`
- `implementation`

每个反例必须说明 construction/scenario、predicted failure、discriminating test、
status 和 evidence。进入 revision 前至少需要：

1. 一个 null 或 alias attack；
2. 一个 regime、boundary、payer 或 measurement attack。

## 8. Root Synthesis

Root agent 不得按多数意见选择路线。Synthesis 必须写：

- 每条 surviving route 的核心假设和 exact gap；
- 哪些路线使用互不相容的假设；
- 哪些 evidence 区分了它们；
- 被拒路线及拒绝理由；
- selected route 和尚未关闭的 proof obligations；
- 下一轮为什么是 exploit、explore、audit 或 stop；
- 什么新证据会改变结论。

没有处理 dissenting route 的 synthesis 无效。

Synthesis 引用的每个 Council result 必须再次通过正式 result validator。validator
会回读 dispatch/task packet，核对 task/route/agent/blind-context 身份、结果 schema、
source hash 和 candidate law；仅让 result 文件与 summary 的 hash 自洽仍然无效。
本地 contract mock 只能标记 `contract_mock_completed`，不得伪装为
`agentic_completed` 或独立研究证据。

## 9. Semantic Verifier

运行：

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_council|pre_revision|pre_promotion|final
```

Verifier 至少检查：

- dual hypothesis 和路线多样性；
- blind independence；
- blocked route 的重开条件；
- passed obligation 的证据；
- counterexample coverage；
- terminal decision 与 loop/handoff/branch 状态一致；
- `promote_official` 至少达到 `component_validated`；
- `payer_validated` 和 `stochastic_validated` 有对应 passed obligations。
- factor proof 的 IC/ICIR、波动损耗、交易成本、回撤和多头端等式；
- risk-premium claim 的 Fama-MacBeth 与 quintile/decile 单调性；
- conjecture、state、factor proof 和 Council synthesis 的 identity/hash lineage；
- root synthesis 使用真实 route/result/law hash，且由主代理显式批准；
- final verifier 重新读取 Council result 文件并计算 SHA256，随后确认 selected law
  确实存在于被选择的 source result，而不只检查一个 64 位字符串。

`pre_promotion` 在任何 official write 前运行，专门关闭“不经过 revision 就直接
promotion”的旁路。它要求 accepted factor proof、measurement validity、
component ablation、反例覆盖和 terminal semantics；Council 最终 synthesis 仍由
`final` 阶段检查。

Verifier 不能判断隐藏 chain-of-thought，也不能证明经济规律。它只验证公开推导、执行证据、
权限、信息集和结论之间是否一致。

### 9.1 Return Label 与 Portfolio Path

预测标签、执行路径和组合 NAV 是三个不同对象。`t+5` 横截面标签可以验证
IC、Fama-MacBeth 和条件分布，但不能按每日观测直接复利，也不能据此推导每日
turnover、volatility 或 drawdown。

正式 metric-verifier v2 只接受 disjoint one-day path：

- horizon 与 holding period 都为 1 个交易日；
- execution timestamp 等于 label start；
- daily rebalance；
- `return_path_mode=daily_one_period_forward_return`；
- 原子面板提供 signal date、label start/end date、label start/end price；
- spec 必须声明 `verification_scope=production`，只引用
  `factorforge_data_access.trade_cal_csv` authority，并锁定由 operator/Data API
  独立解析的原始文件 SHA、规范化 open-date snapshot SHA、显式 snapshot id，
  以及 trusted registry 的 Git anchor commit/blob/SHA；该路径不得位于 factor
  workspace，当前工作树 registry 必须与独立 anchor blob 完全一致；
- kernel 按该日历证明日期及 daily signal coverage 连续，并重算
  `label_end_price/label_start_price-1`。

threshold registration 与 OOS release 必须绑定完整
`evaluation_contract_hash`。该 hash 覆盖 window/label、panel mapping、
portfolio、annualization、cost、Fama-MacBeth 和 bucket 合同。任何多日
overlapping cohort 在缺少独立逐日 holdings/NAV engine 时必须 BLOCK。
仅把 spec 中的 `horizon_days` 改写成 1、用稀疏面板自身日期冒充完整交易日历，
或让 workspace/外部临时目录自己提供未登记的所谓 authoritative calendar、修改
当前 registry 后自报新的 production snapshot、靠 report id 中的 `SMOKE` 改变 scope，
都不构成证明；真实 label 日期、价格、独立日历身份、Git-anchored trusted snapshot
registry 和
forward-return reconciliation 任何一项不一致都
必须 BLOCK。已存在的 threshold registration 只能同内容幂等读取，不能被新合同
覆盖。

## 10. Miner 的 FunSearch 适配

Miner 可以使用 evolution loop，但必须满足：

1. candidate 是可执行 program/Formula-IR/direct-code contract；
2. evaluator 使用 bounded IS exploratory evidence；
3. sealed OOS 不参与选择；
4. 保存 elite、失败和 anti-pattern；
5. 按机制族保留多样性，不能只保留最高 IC；
6. score 必须包含复杂度、换手、覆盖、稳定性和 alias penalty；
7. mutation 必须记录 parent lineage、改变的数学对象和新增自由度；
8. executor report 必须从 source panel 重放每个 program，验证 source/output/
   program hash 和 factor values，手写 factor panel 或伪造 report hash 必须 BLOCK；
9. campaign 必须先冻结 canonical
   `factorforge_miner_data_split_manifest_v1`，绑定 campaign、universe、IS source
   panel hash/日期与全部 sealed OOS panel hash/日期/release state；executor、
   search control、cheap screen、evolution 和 queue 都必须重放该引用与 SHA256，
   当前 source hash 不等于注册 IS 或等于任一 OOS 时 BLOCK；
10. multiplicity 必须真正执行 `BH_FDR` 或 `holm_bonferroni`，并覆盖累计
   `tested_program_hashes` 家族；`gN` 必须绑定 workspace 内 `gN-1`
   canonical search-control 的 SHA256，且 trial ledger 只能追加、不能缩小或
   改写；每代 control 固定写入
   `objects/search_control/search_control__gNN.json`，同代不同内容必须 BLOCK；
   未实现的 deflated-Sharpe/PBO 标签必须 BLOCK；
11. source panel 必须在 campaign workspace；四分位端点使用 value-based
    quantile，相同 factor ties 不得按行顺序拆分；
12. queue builder 必须重放 executor、全部 cheap-screen 数值及 multiplicity，
    不能相信可编辑 summary 中的 `multiplicity_pass` 或 winner 标记；
13. 只有 adjusted p-value 通过预注册 alpha 的候选可进入 queue；
14. cheap-screen winner 只能进入正式 research queue，不能 promotion。

split manifest 和 search-control hash chain 是本地 tamper-evident 合同，不是外部
trusted timestamp，也不等价于让 agent 无法读取文件；其作用是阻止事后把已登记
OOS 重标成 IS，并让这种改写可机检。

## 10.1 Ultimate Dry-Run Proof 边界

`run_factorforge_ultimate.py --dry-run` 和 Ultimate loop dry-run 必须写：

- `status=DRY_RUN`
- `formal_proof_eligible=false`
- `proof_semantics=execution_plan_only`

loop classifier 只接受 `dry_run=false`、完整 command contract、所有 required
command 实际 `PASS` 的 wrapper proof。包含 Step6 时必须看到真实执行的
`validate_research_protocol_pre_council`。contract smoke 可在明确 smoke scope
继续跑回归，但必须带 `contract_smoke_only=true`，不得清除正式 prewrite block
或作为 promotion evidence。

## 11. 强化学习边界

满足以下条件前，不得称为 RL research agent：

- 有足够多的完整研究 trajectory；
- terminal labels 经 semantic verifier 和独立 reviewer 审核；
- reward 不直接等于 IC/收益；
- OOS 不进入训练反馈；
- action space 是研究动作，例如选路线、选测试、关闭缺口，而不是直接调公式。

在此之前使用 deterministic policy、best-of-N、population search 和 reviewer feedback
更可靠。
