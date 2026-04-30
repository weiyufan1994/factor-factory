> [English Version](README.md)

# FactorForge 因子工厂

FactorForge 是一个面向量化因子研究的 **Step1-Step6 全流程研究系统**。它的目标不是批量跑一堆公式然后挑最高 IC，而是把每个因子当成一个严肃研究对象：读懂来源、形成规格、生成代码、回测验证、归档评价、反思迭代，并把成功与失败经验写入知识库，让后续 agent 越来越会做因子研究。

一句话概括：

> FactorForge = 研报/论文理解 + 因子规格化 + 代码生成 + long-only 回测评价 + Step6 研究员反思 + 知识库持续学习。

## 当前核心入口

正式运行必须使用唯一入口：

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

如果 Step1/Step2 已完成、只需要从 Step3B 重新生成/修改代码并继续评估：

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3b --end-step 6
```

如果只需要重跑 Step4-Step6，也必须仍然使用 wrapper：

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 4 --end-step 6
```

直接运行 `skills/factor-forge-step*/scripts/run_step*.py` 只允许用于 wrapper/debug 修复场景，不能作为正式研究入口。正式运行必须产出 `objects/runtime_context/ultimate_run_report__<report_id>.json`，且状态为 `PASS`，否则不算完整闭环。

## 项目为什么存在

传统因子挖掘很容易滑向三类问题：

- 只看 IC/long-short spread，忽略 long-side 是否真的可投资；
- 只做单次回测，不记录失败原因，下一次 agent 重新踩坑；
- 因子、代码、数据、回测、反思散落在不同地方，无法形成可复用研究资产。

FactorForge 的设计目标是避免这些问题：

- 每个因子必须保留来源、公式、数据、实现、回测、诊断、归档和反思；
- 成功因子进入正式因子库，所有尝试进入普通因子库；
- 失败也必须写入知识库，沉淀 anti-pattern 和 kill criteria；
- Step6 负责像研究员一样思考，而不是只当日志记录器。

## Step1-Step6 总流程

### Step1：来源理解与 idea 抽取

输入研报、论文、公式来源或人工想法。Step1 负责识别作者想表达的因子 thesis，并生成：

- `alpha_idea_master__<report_id>.json`
- 初步随机对象、目标统计量、信息集、收益来源假设
- 与历史案例相关的初步线索

Step1 的目标不是抄公式，而是理解“作者为什么认为这个因子能赚钱”。

### Step2：因子规格化

Step2 把 Step1 的想法变成机器可读的 canonical spec，生成：

- `factor_spec_master__<report_id>.json`
- `handoff_to_step3__<report_id>.json`

它要保留：

- 因子公式与字段定义；
- 目标预测对象；
- 经济机制；
- 预期失效模式；
- 可复用想法种子。

### Step3A：数据入口与执行契约

Step3A 不应该每次重新清洗全量数据。它默认读取共享 clean data layer，并生成 report-level slice / local inputs。

原则：

- 清洗数据是基础设施，不是每个因子的重复步骤；
- Step3A 使用固定数据入口；
- 只有用户明确要求刷新/同步数据时，才更新 shared clean layer。

### Step3B：因子表达式与代码实现

Step3B 根据 `factor_spec_master` 和 Step3A 数据契约生成/修改 factor implementation，并在可能时产出 first-run factor values。

它负责：

- 生成因子代码；
- 产出 factor values；
- 写出 Step4 handoff；
- 在 Step6 要求 iterate 时接收 revision proposal 并修改因子表达式/代码。

### Step4：执行、回测与诊断

Step4 负责正式执行因子、生成标准回测证据和诊断 payload。

它应输出：

- IC / Rank IC / IR；
- decile/quantile diagnostics；
- long-side NAV、return、Sharpe、drawdown、recovery；
- turnover；
- trading cost，默认 `turnover * 0.3%`；
- cost-adjusted long-side evidence；
- backend payloads 与图表。

注意：decile、long-short、short leg 只用于诊断，不能作为入库依据。

### Step5：case close 与初步验收

Step5 消费 Step4 证据，生成：

- `factor_case_master__<report_id>.json`
- `factor_evaluation__<report_id>.json`
- `handoff_to_step6__<report_id>.json`
- archive bundle

Step5 必须检查 Step4 结果是否完整、是否明显异常。缺少 long-side Sharpe、drawdown、recovery、turnover、cost 等核心证据时，不能给出 `validated`。

### Step6：研究员反思、知识写回与循环控制

Step6 是 FactorForge 的研究员大脑。它不重新计算原始指标，而是读取 Step4/Step5 证据，检索历史知识库，形成研究判断，并决定：

- `promote_official`
- `promote_candidate`
- `iterate`
- `reject`
- `needs_human_review`

Step6 必须写回研究结论、失败经验、可复用模式和下一步 revision proposal。

## Long-only 研究原则

FactorForge 当前采用 long-only 研究口径：

- 不允许卖空；
- 不允许直接买卖 decile；
- 不允许因为 long-short spread 好就入库；
- 不允许因为 short side 强就说因子成功；
- 不允许通过修改 portfolio expression、rebalance mechanics 或 short-leg 规则来“修复”因子。

正式判断只看：高因子值一侧是否能产生可解释、可持续、风险调整后可接受的 long-side 收益。

如果因子 IC 好但 high-score long side 不赚钱，Step6 应该选择 `iterate` 或 `reject`，不能 promotion。

## 因子作为一门生意

Step6 使用 “factor-as-business” 视角评价因子：

- `revenue`：long-side return / risk premium；
- `COGS`：明确交易成本，默认 `turnover * 0.3%`；
- `volatility`：经营不稳定性 / 风险资本压力；
- `volatility_drag`：几何增长拖累，使用 `-0.5 * sigma^2`；
- `max_drawdown`：资本减值 / capital impairment；
- `recovery_time`：回撤修复期 / payback period；
- `risk_budget`：由 Sharpe、回撤、恢复期、容量和可重复性信心决定。

默认治理阈值：

- candidate：long-side Sharpe >= `0.50`；
- official：long-side Sharpe >= `0.80`；
- drawdown soft limit：max drawdown 不差于 `-35%`；
- recovery soft limit：不超过 `252` 个交易日。

这些阈值是治理默认值，不是永恒真理；未来可按资产类别、流动性、频率、组合位置调整。

## Step6 与知识库如何配合

Step6 与知识库的关系是：**Step6 是研究员大脑，知识库是长期记忆**。

完整闭环如下：

```text
Step4/5 产出证据
    ↓
Step6 读取证据 + 检索知识库
    ↓
Step6 做研究判断：promote / iterate / reject
    ↓
Step6 写回知识库、因子库、研究迭代记录
    ↓
下一次 Step6 再检索这些经验，指导新因子或下一轮修改
```

### 知识库的两层结构

人类可读知识库：

```text
knowledge/因子工厂/
```

包括：

- `正式因子库/`
- `普通因子库/`
- `知识库/`
- `研究迭代/`
- `Agent/`
- `仪表盘/`

机器可读对象层：

```text
factorforge/objects/research_knowledge_base/
factorforge/objects/factor_library_all/
factorforge/objects/factor_library_official/
factorforge/objects/research_iteration_master/
factorforge/objects/research_journal/
```

Markdown 层用于人类阅读、复盘和长期研究笔记；JSON 对象层用于脚本、validator、retrieval 和 agent 自动消费。

### Step6 如何读取知识库

Step6 在正式判断前应先检索类似历史案例，而不是只盯当前指标。

它要查：

- 有没有同类公式；
- 有没有相似 return source；
- 有没有类似失败模式；
- 有没有曾经成功的 revision operator；
- 有没有 long-short 好但 long-side 不行的案例；
- 有没有同一 factor family 的适用 regime 或失效 regime。

例如研究一个量价类 Alpha 时，Step6 应该问：

- 过去量价反转类因子是否多靠 short side？
- 哪些变换曾经改善 high-score long side？
- 是否存在成交量异动、波动、流动性约束、机构行为等可解释机制？
- 这个模式更像风险溢价、信息优势，还是约束驱动套利？

### Step6 如何写回知识库

每次 serious run 都必须写回经验，而不只是保存状态。

应写回：

1. 因子案例记录

```text
knowledge/因子工厂/普通因子库/<report_id>.md
knowledge/因子工厂/正式因子库/<report_id>.md
```

普通因子库记录所有尝试；正式因子库只记录通过高标准的因子。

2. 研究知识记录

```text
knowledge/因子工厂/知识库/<report_id>.md
factorforge/objects/research_knowledge_base/knowledge_record__<report_id>.json
```

这里要写：

- transferable patterns；
- anti-patterns；
- failure regimes；
- revision insights；
- reuse instructions；
- innovative idea seeds。

3. 研究迭代记录

```text
knowledge/因子工厂/研究迭代/<report_id>.md
factorforge/objects/research_iteration_master/research_iteration_master__<report_id>.json
```

这里记录：

- 第一版因子是什么；
- Step4/5 发现什么；
- Step6 为什么 promote / iterate / reject；
- 下一轮修改方向；
- kill criteria；
- 哪些经验未来可复用。

### Step6 的 research memo 必须回答什么

Step6 的 `research_memo` 应至少包括：

- `formula_understanding`
- `return_source_hypothesis`
- `metric_interpretation`
- `evidence_quality`
- `failure_or_risk_analysis`
- `decision_rationale`
- `next_research_tests`
- `math_discipline_review`
- `learning_and_innovation`
- `experience_chain`
- `revision_taxonomy`
- `program_search_policy`

核心不是“这个因子跑完了”，而是回答：

> 这次研究让我们对因子、市场结构、收益来源、失败模式和下一次创新多理解了什么？

### Math discipline review

Step6 必须执行数学纪律检查：

- `step1_random_object`：研究对象是什么；
- `target_statistic`：因子到底预测什么统计量；
- `information_set_legality`：是否使用未来信息；
- `spec_stability`：公式是否稳定；
- `signal_vs_portfolio_gap`：信号和可投资组合收益之间是否断裂；
- `revision_operator`：修改算子是什么；
- `generalization_argument`：为什么不是过拟合；
- `overfit_risk`：过拟合风险；
- `kill_criteria`：停止条件。

如果这些问题答不出来，不能 promote official。

### Step6 如何驱动下一轮修改

如果 Step6 判断 `iterate`，它不能直接随意改代码。正确流程是：

```text
Step6 revision proposal
    ↓
人工审批
    ↓
Step3B 修改因子表达式/代码
    ↓
Step4 重新回测
    ↓
Step5 case close
    ↓
Step6 再反思
```

revision proposal 必须说明：

- 要改哪个 factor expression；
- 修改强化哪个 return source；
- 为什么更符合经济线性/单调关系；
- 目标改善 long-side Sharpe、drawdown、recovery 还是 monotonicity；
- 下一轮成功标准；
- kill criteria；
- 是否需要 Bayesian 参数搜索、遗传公式变异、多 agent 并行探索。

## Program Search 是补充，不是替代研究员

Step6 可以使用 program search，但不能让算法替代研究判断。

支持的模式包括：

- Bayesian parameter search：在 thesis 不变时做局部参数搜索；
- genetic formula mutation：在公式空间中探索相邻表达；
- reinforcement-learning advisory：当积累足够 trajectories 后学习 revise/promote/reject policy；
- multi-agent parallel exploration：多个 agent 同时探索不同解释或修改方向。

搜索分支必须先有：

- return-source analysis；
- market-structure hypothesis；
- knowledge-base priors；
- success criteria；
- falsification tests；
- human approval。

算法搜索只能提供候选证据，不能直接写 canonical Step3B 或 promote。

## 数据规则

FactorForge 默认复用 shared clean layer：

- 不按因子重复全量清洗；
- `build_clean_daily_layer.py` 不是每个因子的必跑步骤；
- 数据刷新必须由用户明确授权；
- Step3A 使用 clean layer + report-level slice；
- Mac / EC2 应通过同步机制共享 clean data 与知识库状态。

## 仓库结构

重要目录：

```text
scripts/                              # ultimate wrapper、数据工具、治理工具
skills/factor-forge-step1/             # Step1 skill
skills/factor-forge-step2/             # Step2 skill
skills/factor-forge-step3/             # Step3 skill
skills/factor-forge-step4/             # Step4 skill
skills/factor-forge-step5/             # Step5 skill
skills/factor-forge-step6/             # Step6 skill
skills/factor-forge-ultimate/          # 顶层 orchestration skill
skills/factor-forge-researcher/        # 全流程研究员层
skills/factor-forge-step6-researcher/  # Step6 深度研究员层
skills/factor-forge-research-brain/    # 投资逻辑与反思框架
factor_factory/data_access/            # 共享数据访问层
knowledge/因子工厂/                    # Obsidian 风格人类知识库
factorforge/objects/                   # 本地 runtime object 层，通常不进入 git
factorforge/runs/                      # 本地运行输出，通常不进入 git
factorforge/evaluations/               # 本地评估输出，通常不进入 git
```

## 常用命令

安装本地包：

```bash
python3 -m pip install -e .
```

安装 Step4 / qlib 相关依赖：

```bash
python3 -m pip install -e ".[step4]"
python3 -m pip install -e ".[qlib]"
```

构建 runtime context：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

正式运行：

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

构建知识库检索索引：

```bash
python3 scripts/build_factorforge_retrieval_index.py
```

导出 Obsidian 知识库：

```bash
python3 scripts/export_factorforge_obsidian.py
```

查询知识库：

```bash
python3 scripts/query_factorforge_retrieval_index.py --query "long-side monotonicity failure" --top-k 5
```

## 治理规则

- 正式 workflow 只能走 `run_factorforge_ultimate.py`；
- legacy/sample/debug writer 不能写 canonical artifacts；
- `objects/`、`runs/`、`evaluations/`、`generated_code/`、`archive/`、`factorforge/`、`data/clean/`、`data/raw/` 默认不提交；
- Step5 validated 必须依赖完整 long-side risk-adjusted evidence；
- Step6 promotion 必须通过知识库检索、数学纪律、long-only 研究口径和 risk-adjusted long-side 阈值；
- 任何新 canonical writer 都必须经过架构审查。

## 推荐阅读路径

1. `skills/factor-forge-ultimate/SKILL.md`
2. `skills/factor-forge-step6/SKILL.md`
3. `skills/factor-forge-research-brain/SKILL.md`
4. `docs/contracts/README.zh-CN.md`
5. `docs/contracts/step6-contract.zh-CN.md`
6. `docs/operations/factorforge-math-research-discipline.zh-CN.md`
7. `knowledge/因子工厂/Home.md`
8. `knowledge/因子工厂/知识库/因子迭代方法论.md`

