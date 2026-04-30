# 因子工厂统一 Calling Convention

## 目的
为了让本地 Codex、EC2 上的 Humphrey、以及后续 Bernard/其他 agent 用同一种方式接任务，这里定义一套统一的调用口径。

这套约定的目标不是限制灵活性，而是减少：
- 口径漂移
- 步骤遗漏
- 数据同步误解
- “默认假设”不一致

## 一句话原则
以后给因子工厂下任务，优先明确这 6 项：
1. 目标
2. 对象
3. 起点
4. 边界
5. 数据口径
6. 产出

## 标准模板
```text
目标：
对象：
起点：
边界：
数据口径：
产出：
```

## 六项字段解释
### 1. 目标
这次任务希望达成什么。

示例：
- 复现一篇研报因子
- 优化已有因子
- 跑完整 Step3-6 闭环
- 只做 Step4 判断卡
- 只做 Step5/6 知识归档

### 2. 对象
本次研究对象是谁。

可选形式：
- `report_id=...`
- 一份 PDF
- 一个已存在因子名
- 一个 case id

示例：
- `report_id=DONGWU_TECH_ANALYSIS_20200619_02`
- `PDF=/Users/humphrey/Documents/...pdf`
- `factor_id=UBL`

### 3. 起点
从哪一步开始，而不是默认总从 Step1 开始。

示例：
- 从 Step1 开始
- 从 Step3B 开始
- 从 Step4 开始
- 从 Step6 开始
- 跑完整 Step1-6

### 4. 边界
明确哪些事情不能自动做，或者必须先确认。

示例：
- 不要同步数据
- 不要自动改代码
- 改代码前先出 revision proposal
- 不要进 Step5
- 不要跑 qlib native

### 5. 数据口径
明确这次是否允许更新/同步数据，以及优先用哪层数据。

推荐表达：
- 优先复用 EC2 持久数据
- 先用本地缓存，不要重新同步
- 允许同步 daily_basic，但不要碰 minute
- 允许通过 Tailscale 连接 Mac 数据

### 6. 产出
明确最终想看到什么，而不是只说“跑一下”。

示例：
- 给我一页判断卡
- 给我 Step6 revision proposal
- 给我正式归档结果
- 给我失败签名和修补单
- 给我 promote / iterate / reject 结论

## 推荐默认假设
如果调用者没有特别说明，系统默认：
1. 优先复用已有数据，不主动全量同步。
2. 优先走 repo 里的统一实现，不单独发明 skill 私有逻辑。
3. 能自动跑完的步骤尽量自动跑完。
4. 涉及因子修改时，先产出 revision proposal，再等待人工批准。
5. 输出至少包含：当前状态、关键证据、下一步建议。

## 数据权限硬规则
1. Bernard / Humphrey / researcher agent 默认只允许读取 shared clean layer，不允许私自同步、重建、替换或增强数据层。
2. 只有用户明确要求 Codex 更新数据时，才允许执行 raw/clean data mutation。
3. 会改写 shared clean layer 的脚本必须使用显式授权：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved \
python3 <data-script>.py ... --operator codex
```

4. 因子研究任务默认不得调用临时数据处理脚本；Step3A 只 materialize report-scoped inputs，不能重洗全量数据。
5. 如果数据缺字段或过期，agent 必须报告缺口并等待 Codex 数据更新，不得自行改数据。

## 示例
### 示例 1：只做 Step4 判断
```text
目标：判断这条因子是否值得继续优化
对象：report_id=DONGWU_TECH_ANALYSIS_20200619_02
起点：Step4
边界：不要自动改代码；不要直接进 Step5
数据口径：优先复用 EC2 持久数据，不要重新同步
产出：一页判断卡
```

### 示例 2：做审批式自动 loop
```text
目标：让这条因子进入 Step6 自动闭环
对象：report_id=DONGWU_TECH_ANALYSIS_20200619_02
起点：Step6
边界：如果需要改代码，必须先出 revision proposal 等我批准
数据口径：优先用本地已有预处理结果
产出：Step6 proposal + 下一轮修改方向
```

### 示例 3：完整复现一篇新研报
```text
目标：从 PDF 复现一个新因子并跑到 Step5
对象：PDF=/Users/humphrey/Documents/factor factory/因子研报/xxx.pdf
起点：Step1
边界：先不要进 Step6
数据口径：daily 可同步，minute 暂时不要同步
产出：Step5 case + lessons + next_actions
```

## 最短可用模板
如果不想写太长，至少给这四项：
```text
目标：
对象：
起点：
约束：
```

示例：
```text
目标：验证这条因子是否值得继续优化
对象：DONGWU_TECH_ANALYSIS_20200619_02
起点：Step4
约束：不要同步数据；如果要改代码先出 proposal
```

## 对系统分层的补充说明
当前推荐理解是：
- repo = 共享真相层
- skills = 公共入口和编排层
- Bernard on Mac = `FactorForge Researcher Agent`，负责 researcher-led 研究连续性、Mac BGE-M3 检索、Obsidian 因子工厂维护
- EC2 = 重计算与长任务执行层

所以这份 calling convention 不是给某一个 agent 专用的，而是给整套因子工厂统一使用的。

## FactorForge Researcher Agent 默认口径

正式因子研究默认由 Mac 上的 Bernard 作为 `FactorForge Researcher Agent` 统筹。

默认要求：
1. 每个因子都 researcher-led，不走机械批量跑。
2. Step1/2 必须理解作者或论文原始 thesis。
3. Step3 必须检查数据与实现是否忠实保留 thesis。
4. Step4 必须解释 metric、图表和可交易性。
5. Step5/6 必须沉淀到普通因子库、正式因子库和知识库。
6. 失败因子也必须写入普通因子库和知识库。
7. Obsidian vault 固定为 `/Users/humphrey/projects/factor-factory/knowledge/因子工厂`。

## 系统能力台账

当用户讨论的是 Factor Forge 系统能力建设，而不是单个因子 case 时，Bernard / Humphrey 应查看并维护：

- `docs/operations/factorforge-capability-ledger.zh-CN.md`
- `knowledge/因子工厂/Agent/FactorForge 能力台账.md`

当前必须登记和追踪的能力建设项：

1. `PROGRAM_SEARCH_ENGINE_V1`：把 Step6 的遗传算法、贝叶斯搜索、RL advisory 和多 agent 并行探索，从文字策略升级为可执行 branch system。
2. `GOLDEN_CASE_REGRESSION_V1`：用 Alpha001/002/010/012/UBL-or-CPV 等固定案例，验证 workflow / skill / repo 一致性。
3. `PORTFOLIO_SIGNAL_SYNTHESIS_BACKLOG`：记录为 Factor Forge 之后的下一层系统，不混入当前单因子 Step1-6 主闭环。
4. `AGENT_ORCHESTRATION_V1`：先做轻量任务台账，再做 manager script，最后再考虑常驻 scheduler/dashboard。

轻量任务台账入口：

```bash
python3 scripts/factorforge_task_ledger.py create ...
python3 scripts/factorforge_task_ledger.py update --task-id <task_id> ...
python3 scripts/factorforge_task_ledger.py list
python3 scripts/factorforge_task_ledger.py validate
```

凡是跨 agent、跨机器、需要人工审批、或可能长时间运行的因子工厂任务，都应该先登记任务台账。台账只记录状态，不授权任何数据 mutation 或代码修改。
