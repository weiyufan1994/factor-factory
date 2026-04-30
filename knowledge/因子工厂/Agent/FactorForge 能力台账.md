---
tags:
  - factorforge
  - agent
  - capability-ledger
updated: 2026-04-26
---

# FactorForge 能力台账

这份台账记录 Factor Forge Ultimate 还需要继续建设的系统能力。它不是单个因子的研究结论，而是给 Bernard / Humphrey / Codex 的长期施工清单。

## 当前判断

Factor Forge Ultimate 已经可以作为 researcher-led 单因子研究闭环使用：Step1/2 理解原始 thesis，Step3 生成数据/代码，Step4 固化评估证据，Step5 做质量门，Step6 做反思、知识写回和迭代决策。

但它还不是完全自主的量化基金经理。下一阶段要把搜索、回归测试、组合层、agent 调度继续工程化。

## 0. Runtime Context / 标准路径接口

状态：V1 已启动。

新增能力：

- `factor_factory/runtime_context.py`：统一 Factor Forge runtime root、objects、runs、evaluations、archive、clean data、handoff、branch artifact 路径；
- `scripts/build_factorforge_runtime_context.py`：生成 `runtime_context__<report_id>.json` manifest；
- `docs/contracts/factorforge-runtime-context-contract.zh-CN.md`：标准路径接口契约。

目的：以后每个 skill / step 不再自己到处搜索地址，而是先通过 runtime context 拿 canonical path。

已接入：

- `run_program_search_bayesian_worker.py`

后续要求：

- Bernard / Humphrey 新增 worker 时，不要复制新的 `LEGACY_WORKSPACE` 和 path candidates；
- 修改 shared ledger 必须用 locked update；
- 普通 JSON 写入使用 atomic write；
- 如果自然语言回报路径问题，必须说明当前使用的 `factorforge_root` 和 manifest 路径。

## 1. Program Search Engine V1

状态：V1 scaffold 已启动。

当前新增能力：

- `build_program_search_plan.py`：把 Step6 研究判断转成 program search plan；
- `validate_program_search_plan.py`：验证每个搜索分支是否坚持 researcher-first，而不是纯 data mining。
- `approve_program_search_branch.py`：记录人工批准/拒绝某个搜索分支。
- `prepare_approved_search_branch.py`：为批准分支生成隔离工作目录和 taskbook。
- `run_program_search_audit_worker.py`：内置审计 worker，检查本地证据链、handoff、artifact、信息集和合约漂移。
- `run_program_search_bayesian_worker.py`：内置贝叶斯/局部参数搜索 worker，只在已批准的 exploit 分支里运行。
- `validate_bayesian_search_trials.py`：验证贝叶斯 trial 是否保留参数、指标、失败签名、overfit / falsification 判断和人工审批闸门。
- `record_search_branch_result.py`：把子代理/算法分支结果写成统一 result object。
- `validate_search_branch_result.py`：验证分支结果是否包含反证、overfit、证据或失败签名。
- `merge_program_search_branches.py`：由 Step6 生成 advisory 合并报告，不自动改代码。

注意：这些脚本只在批准分支内执行或记录结果，不自动改 Step3B、不动 shared clean data。`run_program_search_bayesian_worker.py` 即使找到更好的参数，也只能写入 branch result，不能自己宣布入库。

外部方法启发已登记：

- `FactorMiner`：经验记忆、成功模式、失败约束、retrieve/generate/evaluate/distill；
- `FactorEngine`：逻辑修改与参数优化分离，Bayesian 只负责 micro 参数；
- `CogAlpha` / `QuantaAlpha`：LLM reasoning + evolution mutation / recombination；
- `AlphaSAGE`：结构感知、多样性、低相关因子库目标；
- `AutoAlpha` / Quality-Diversity：避开已探索拥挤区域，记录失败区域。

实现优先级：

1. Bayesian parameter worker：已启动 V1。
2. Evolution / GA worker：下一步。
3. Quality-Diversity / novelty gate：下一步。
4. RL / GFlowNet：中长期，先积累 revision trajectories。

目标：把 Step6 里的遗传算法、贝叶斯搜索、强化学习建议、多 agent 并行探索，从“方法名”变成真正可执行的 branch system。

要求：

- 每个分支必须有 `branch_id`、父版本、假设、修改目标、预算、kill criteria、artifact list；
- 遗传算法用于公式结构搜索，必须记录失败个体，不能 cherry-pick；
- 贝叶斯搜索用于窗口、阈值、decay、neutralization strength 等参数搜索，必须有 OOS 校验；
- 强化学习短期只做 advisory，等积累足够 revision trajectories 后再考虑正式 policy；
- 多 agent 并行探索应固定为 exploit / explore / portfolio / audit 四类分支；
- 所有分支最终由 Step6 合并比较，不能由分支 agent 自己宣布胜利。

## 2. Golden Case Regression V1

目标：用固定案例钉住 workflow / skill / repo 的一致性，防止不同 agent 对流程理解漂移。

首批建议：

- `ALPHA001_PAPER_20100104_CURRENT`
- `ALPHA002_PAPER_20160101_20250711`
- `ALPHA010_PAPER_20160101_20250711`
- `ALPHA012_PAPER_20160101_20250711`
- `DONGWU_TECH_ANALYSIS_20200619_02` 或 UBL/CPV

每个 golden case 要固定：

- 入口从 Step1 / Step3 / Step4 哪一步开始；
- 每步必须存在的 artifact；
- validator 的 PASS/WARN/BLOCK 预期；
- Step4 标准图表和 metrics；
- 关键指标 tolerance；
- 禁止触发 shared clean data mutation；
- skill.md 描述必须能映射到 repo 真实脚本。

## 3. Portfolio / Signal Synthesis Backlog

这是 Factor Forge 之后的下一层系统。

当前 Step4/Step6 只负责判断单因子是否可交易，以及在信号好但组合变现差时提出 portfolio expression repair。

真正的 multi-factor signal synthesis、risk model、portfolio optimizer、capital allocation 应另建 Portfolio Forge / Signal Forge，不应混进当前单因子 Step1-6 主闭环。

未来要做：

- 因子相关性和冗余检测；
- 正式因子库组合选择；
- 多因子信号合成；
- 风格/行业/市值/流动性风险约束；
- 交易成本和容量模型；
- PM 级组合决策报告。

## 4. Agent Orchestration V1

目标：解决 Bernard / Humphrey / Codex 目前主要靠 prompt 驱动的问题。

状态：Phase A lightweight ledger 已启动。

当前新增能力：

- `scripts/factorforge_task_ledger.py`：创建、更新、展示、列表和验证任务台账。

边界：Phase A 只记录任务状态，不自动调度、不启动任务、不改数据、不绕过审批。

阶段计划：

- Phase A：轻量任务台账，记录 task_id、report_id、owner、current_step、status、exit code、artifact、failure signature、approval checkpoint；
- Phase B：manager script，自动调用 Step 脚本、tail log、跑 validator、有限重试、遇到权限/审批点停止；
- Phase C：常驻 scheduler/dashboard，支持多 agent 状态、EC2 heavy compute、Mac knowledge sync、branch search 并行调度。

当前建议先做 Phase A 和 Golden Case，不要直接跳到大型调度器。

## 给 Humphrey 的执行要求

Humphrey 看到本台账后，应把下面四项作为系统建设任务登记：

1. `PROGRAM_SEARCH_ENGINE_V1`
2. `GOLDEN_CASE_REGRESSION_V1`
3. `PORTFOLIO_SIGNAL_SYNTHESIS_BACKLOG`
4. `AGENT_ORCHESTRATION_V1`

除非用户明确要求，Humphrey 不要自行修改 shared clean data，不要把临时实验图冒充 Step4 官方证据，不要在没有 Step6 revision proposal 和用户批准的情况下改 Step3B 因子代码。
