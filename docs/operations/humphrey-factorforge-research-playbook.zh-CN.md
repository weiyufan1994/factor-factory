# Humphrey 因子工厂研究操作手册

## 这份文档是干什么的
推荐总入口 skill：`skills/factor-forge-ultimate/SKILL.md`。

如果需要把 Step1-6 当成一个完整研究系统来调用，优先使用这个 ultimate skill；其中 review 和 revision proposal 视为 Step6 的组成部分。


这是一份给 Humphrey 的完整上手文档。

目标只有一个：

- 让 Humphrey 能够独立、稳定、可复现地使用因子工厂做研究
- 不再依赖聊天碎片记忆
- 不再在数据层、执行层、知识层各自发明一套新逻辑

一句话原则：

> repo 是共享真相层，skills 是公共入口层，研究结论最终写回因子库和知识库。

硬规则：

> 正式研究只能通过 `scripts/run_factorforge_ultimate.py`；direct step scripts are isolated debug only and blocked for canonical writes.

---

## 总体心智模型

把因子工厂理解成四层：

1. 数据层
- 原始数据
- 共享清洗层
- report 级切片

2. 执行层
- Step3 写或修改实现
- Step4 跑评估

3. 收口层
- Step5 归档 case
- Step6 反思、决策、控制 loop

4. 知识层
- 全部因子库
- 正式因子库
- 统一知识库
- Obsidian 工作台
- retrieval / embedding 检索层

以后做任何 case，都优先问自己三件事：

1. 我现在在哪一层？
2. 这层的标准输入输出是什么？
3. 结果最终有没有写回知识层？

还要问第四件事：

4. 这次研究有没有让未来的 researcher agent 更聪明？

---

## 目录与系统边界

### 1. repo：共享真相层

路径：

- `/home/ubuntu/.openclaw/workspace/repos/factor-factory`

这里维护：

- 数据清洗与预处理
- Step3/4/5/6 正式脚本
- 研究 loop
- 因子库 / 知识库 / 迭代记录
- Obsidian 导出与检索索引

### 2. skills：公共入口层

路径：

- `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step3`
- `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step4`
- `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step5`
- `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step6`

这些脚本现在的正确理解是：

- 它们是 wrapper / 入口
- 真正实现以 repo 为准

### 3. runtime：运行态根目录

路径：

- `/home/ubuntu/.openclaw/workspace/factorforge`

这里存放：

- `data/`
- `runs/`
- `objects/`
- `evaluations/`
- `generated_code/`

---

## 数据层应该怎么理解

### 关键原则

不要每个因子都重新全量清洗数据。

现在已经改成两层：

1. 共享清洗层
- 一次性构建 + 按需更新
- 位置：
  - `/home/ubuntu/.openclaw/workspace/factorforge/data/clean/daily_clean.parquet`
  - `/home/ubuntu/.openclaw/workspace/factorforge/data/clean/daily_clean.meta.json`

2. report 级切片
- 从共享清洗层切出本次 case 需要的 slice
- 位置：
  - `/home/ubuntu/.openclaw/workspace/factorforge/runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.csv`
  - `/home/ubuntu/.openclaw/workspace/factorforge/runs/<report_id>/step3a_local_inputs/daily_input_meta__<report_id>.json`

### 这意味着什么

以前慢是因为：

- 每个因子都在重复做清洗 + 大快照落盘

现在应该是：

- 默认复用已有共享 clean layer
- 只有缺失、覆盖不足，或中堂明确要求更新/同步数据时，才重建共享 clean layer
- 每个 case 默认复用已有 report slice；只有缺失、过期或窗口变化时才重新切 slice
- 再进 Step3/4/5/6

### 日常操作

#### 仅在缺失、覆盖不足，或明确要求时建或更新共享清洗层

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory

/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python scripts/build_clean_daily_layer.py \
  --start 20100104 \
  --end current
```

#### 再切 report 级 slice

默认先检查：

- `runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.csv`
- `runs/<report_id>/step3a_local_inputs/daily_input_meta__<report_id>.json`

如果它们已存在且 metadata 覆盖本次窗口，就不要重复切 slice。
只有缺失、过期或窗口变化时才执行：

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python scripts/preprocess_daily_data.py \
  --report-id "<report_id>" \
  --start 20100104 \
  --end current
```

如果需要 qlib provider：

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python scripts/preprocess_daily_data.py \
  --report-id "<report_id>" \
  --start 20100104 \
  --end current \
  --build-provider
```

---

## Step1-6 到底各负责什么

### Step1
- 确认研究来源与任务目标
- 对 canonical alpha 或经典公式型因子，这一步通常很轻

### Step2
- 把公式或逻辑写成系统认可的 spec
- 如果已经有：
  - `alpha_idea_master`
  - `factor_spec_master`
  - `handoff_to_step3`
  则可以视为 Step2 已完成

### Step3
- 生成或更新执行契约与实现入口
- `Step3A` 现在主要做：
  - 读取 report slice
  - 写 `data_prep_master`
  - 写 `qlib_adapter_config`
  - 写 `implementation_plan_master`
  - 写 `handoff_to_step4`
- `Step3B` 主要做：
  - 生成 `factor_impl_stub`
  - 生成 qlib expression draft
  - 生成 hybrid scaffold
  - 触发首轮 factor run

### Step4
- 产证据，不做研究结论
- 默认 backend：
  - `self_quant_analyzer`
  - `qlib_backtest`
- 这里负责：
  - factor values
  - IC / grouped diagnostics
  - qlib backtest
  - run metadata

### Step5
- 案例收口层
- 负责：
  - `factor_case_master`
  - `factor_evaluation`
  - `lessons`
  - `next_actions`
  - `handoff_to_step6`

### Step6
- 研究反思与 loop 控制层
- 负责：
  - 解释 Step4/5 证据
  - 执行数学研究纪律检查
  - 抽象 transferable pattern / anti-pattern / idea seed
  - 写回知识层
  - 决定：
    - `promote_official`
    - `iterate`
    - `reject`
    - `needs_human_review`
- 如果是 `iterate`：
  - 先生成 `revision_proposal`
  - 等人工批准
  - 再自动修改 Step3B 并重跑下一轮

一句话记忆：

- Step4：产证据
- Step5：归档
- Step6：反思与决策
- Step3B：真正改实现
- 知识库：让下一次研究更聪明

---

## 标准研究闭环

标准顺序：

1. Step3
2. Step3B
3. Step4
4. Step5
5. Step6

若 Step6 判断 `iterate`：

6. 生成 `revision_proposal`
7. 等中堂批准
8. 自动改 Step3B
9. 重跑 Step4/5/6

直到：

- `promote_official`
- `reject`
- 或 `needs_human_review`

---

## Step1 / Step2 的实操入口

### 先判断你面对的是哪一类任务

新任务先分三类：

1. 新研报 PDF
- 例：一篇从未进入因子工厂的研报
- 正确入口：`Step1 -> Step2 -> Step3...`

2. canonical alpha / 经典公式因子
- 例：Alpha001、Alpha002、Alpha101 这类公式明确的因子
- 正确入口：若对象已存在，可直接从 `Step3` 开始

3. 已经做过一轮的旧 case
- 例：已有 `factor_spec_master`、已有 `handoff_to_step3`
- 正确入口：直接从 `Step3`、`Step4`、`Step5` 或 `Step6` 开始

### Step1 什么时候必须跑

必须跑 `Step1` 的情况：

- 只有 PDF，没有 `alpha_idea_master`
- 你还不知道报告到底在讲什么因子
- 你需要把报告逻辑变成系统认可的 canonical alpha idea

可以跳过 `Step1` 的情况：

- canonical alpha 公式本身已经非常明确
- 已经有 `alpha_idea_master__{report_id}.json`

### Step2 什么时候必须跑

必须跑 `Step2` 的情况：

- 已经有 `alpha_idea_master`
- 但还没有 `factor_spec_master`
- 还没有 `handoff_to_step3`

可以跳过 `Step2` 的情况：

- 已经有：
  - `factor_spec_master__{report_id}.json`
  - `handoff_to_step3__{report_id}.json`

### Step1 完成的判定标准

至少应有：

1. `alpha_idea_master`
2. `handoff_to_step2`
3. primary / challenger intake 与 thesis 相关对象

如果没有 `alpha_idea_master`，不能说 Step1 完成。

### Step2 完成的判定标准

至少应有：

1. `factor_spec_master`
2. `handoff_to_step3`
3. `factor_spec_raw__primary`
4. `factor_spec_raw__challenger`
5. `factor_consistency`

如果没有 `factor_spec_master + handoff_to_step3`，不能说 Step2 完成。

### 新研报 PDF 的推荐路径

如果中堂给你一篇新 PDF，先按这个顺序：

1. 跑 Step1，得到 `alpha_idea_master`
2. 跑 Step2，得到 `factor_spec_master`
3. 再进 Step3-6

### canonical alpha 的推荐路径

如果中堂给你的是 Alpha001 / Alpha002 这类 canonical alpha：

1. 若对象还没建，补齐：
  - `alpha_idea_master`
  - `factor_spec_master`
  - `handoff_to_step3`
2. 对象齐了以后，不要反复纠缠 Step1/2
3. 直接从 Step3 开始完整闭环

---

## canonical alpha 应该怎么跑

像 Alpha001、Alpha002 这种公式明确的 canonical alpha，不要把它当“需要重新做复杂语义拆解”的研报因子。

正确做法：

1. 视为 Step1/2 已基本完成
2. 确认已有：
  - `alpha_idea_master`
  - `factor_spec_master`
  - `handoff_to_step3`
3. 直接从 Step3 开始
4. 跑完整 Step3 -> Step6

Alpha001 已经证明这条路是可行的，而且已经正式进入官方库。

---

## Humphrey 最常用的命令

### 0. Step1 / Step2 入口命令与动作

#### Step1：新研报 PDF 入口

Step1 当前不是“一条统一 shell 命令包打天下”，而是一个 `pdf/tool + chief merge + 对象写回` 的流程。

你应该这样理解：

1. 用 `skills/factor-forge-step1/SKILL.md` 的提示词跑 primary intake
2. 跑 challenger intake
3. 跑 chief merge
4. 写 `alpha_idea_master`
5. 确认 `handoff_to_step2`

阅读入口：

- `/home/ubuntu/.openclaw/workspace/repos/factor-factory/skills/factor-forge-step1/SKILL.md`

你至少要确认最终落盘：

- `factorforge/objects/alpha_idea_master/alpha_idea_master__<report_id>.json`

#### Step2：把 alpha idea 变成 factor spec

正式 Step2+ 必须通过 ultimate wrapper：

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory
python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 2 --end-step 6
```

Step2 跑完后至少要检查：

- `factorforge/objects/factor_spec_master/factor_spec_master__<report_id>.json`
- `factorforge/objects/handoff/handoff_to_step3__<report_id>.json`

如果这两个不存在，就不要继续进 Step3。

### A. 预处理

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory

/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python scripts/build_clean_daily_layer.py \
  --start 20100104 \
  --end current

/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python scripts/preprocess_daily_data.py \
  --report-id "<report_id>" \
  --start 20100104 \
  --end current
```

### B. Step3 / Step3B

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory
python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 3 --end-step 6
```

### C. Step4

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory
python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 4 --end-step 6
```

### D. Step5

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory
python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 5 --end-step 6
```

### E. Step6 收口

```bash
cd /home/ubuntu/.openclaw/workspace/repos/factor-factory
python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 6 --end-step 6
```

### F. Debug 附录：direct step / Step6 loop

以下 direct step、controller、autoloop 命令仅限 isolated developer debug，且已对 canonical writes 做 block；不可用于正式 Factor Forge run。

```bash
FACTORFORGE_ALLOW_DIRECT_STEP=1 FACTORFORGE_DEBUG_ROOT=/tmp/factorforge-debug \
python3 /home/ubuntu/.openclaw/workspace/skills/factor-forge-step3/scripts/run_step3.py --report-id "<report_id>"

python3 /home/ubuntu/.openclaw/workspace/skills/factor-forge-step6/scripts/run_step6_autoloop.py --report-id "<report_id>" --max-iterations 1
```

如果生成 proposal，先停，不要直接改代码。

批准后再继续：

```bash
python3 /home/ubuntu/.openclaw/workspace/skills/factor-forge-step6/scripts/approve_step6_revision.py \
  --report-id "<report_id>" \
  --decision approve \
  --notes "中堂的修改意见"

正式继续执行仍然回到：

python3 scripts/run_factorforge_ultimate.py --report-id "<report_id>" --start-step 6 --end-step 6
```

---

## Humphrey 应该如何汇报

以后汇报只按证据，不要先猜原因。

### 成功时至少回

1. 当前跑到哪一步
2. 关键产物是否真实落地
3. `run_status`
4. backend 状态
5. headline metrics
6. 下一步建议

### 失败时只回

1. 完整命令
2. 完整 stdout/stderr
3. 哪一步失败
4. 已落地文件
5. 退出码

不要先说：

- “大概率是数据问题”
- “应该是 SIGTERM”
- “可能是路径问题”

先拿证据，再下结论。

---

## 这几类问题现在已经有标准答案

### 1. `current` 到底是什么

`current` 不是字面字符串终点。  
它表示：

- 跑到当前输入数据里最新可用的交易日

现在系统已经改成：

- 如果 `target_window.end = current`
- 就用本轮输入数据里的最新交易日当作 `effective_target_end`

所以 canonical alpha 不会再因为这个逻辑被无谓地判成 `partial`。

### 2. 为什么不能每个因子都重新清洗

因为：

- 太慢
- 太占空间
- 会让工程噪音盖过研究本身

现在必须优先：

- 共享 clean layer
- report 级轻切片

### 3. 为什么 Step4 必须双 backend

因为：

- 只有 `self_quant`，更像截面信号诊断
- 只有 `qlib_backtest`，更像组合实现诊断

两者都要，研究判断才稳。

### 4. 为什么 Step6 不直接乱改代码

因为：

- 研究方向需要人工把关
- 中堂可能会给额外投资理解
- 自动 loop 只能在批准后进行

所以现在的规则是：

- `iterate` -> 先提案
- 中堂批准
- 再自动改 Step3B

---

## 因子库、知识库、Obsidian 分别是什么

### 全部因子库

路径：

- `/home/ubuntu/.openclaw/workspace/factorforge/objects/factor_library_all`

记录所有尝试，包括成功和失败。

### 正式因子库

路径：

- `/home/ubuntu/.openclaw/workspace/factorforge/objects/factor_library_official`

只放 `promote_official` 的因子。

### 知识库

路径：

- `/home/ubuntu/.openclaw/workspace/factorforge/objects/research_knowledge_base`

记录：

- success patterns
- failure patterns
- modification hypotheses

### 迭代记录

路径：

- `/home/ubuntu/.openclaw/workspace/factorforge/objects/research_iteration_master`

记录每轮：

- evidence summary
- research judgment
- loop action

### Obsidian vault

本地工作台路径：

- `/Users/humphrey/projects/factor-factory/knowledge/obsidian_vault`

它适合人看、做研究笔记、形成基金经理式知识沉淀。

---

## Mac 和 EC2 怎么共享知识

原则：

- EC2 跑研究主链
- Mac 做知识中枢和阅读工作台

已经有同步工具：

- `/home/ubuntu/.openclaw/workspace/repos/factor-factory/scripts/sync_factorforge_knowledge_bundle.py`

本地同名脚本：

- `/Users/humphrey/projects/factor-factory/scripts/sync_factorforge_knowledge_bundle.py`

推荐模式：

1. EC2 跑完 Step5/6
2. 打 bundle
3. 回灌到 Mac
4. 本地重建：
  - retrieval index
  - Obsidian vault

这样两边吃的是同一套知识，而不是各记各的。

---

## Humphrey 处理新 canonical alpha 的推荐指令

如果中堂让你做 `alpha002` 这类新 canonical alpha，按这个口径接：

```text
目标：按 canonical alpha 公式跑完整研究闭环
对象：ALPHA002_...
起点：Step3
边界：优先复用共享 clean layer；如要自动修改先出 proposal 再等中堂批准
数据口径：不要重复全量清洗；优先用已有 clean layer
产出：Step4 结果 + Step5/6 收口判断
```

---

## 你最应该记住的 10 条纪律

1. repo 是真相层，skills 是入口层。
2. 不要每个因子重新全量清洗。
3. canonical alpha 默认从 Step3 开始。
4. Step4 默认双 backend。
5. Step6 才做研究判断。
6. 真改代码的是 Step3B。
7. 自动修改前必须先出 proposal。
8. 失败先贴日志，不先猜原因。
9. 跑完研究一定写回知识层。
10. EC2 跑研究，Mac 做知识中枢。

---

## 一句话总结

Humphrey 使用因子工厂的正确方式，不是“帮中堂多跑几个脚本”，而是：

> 用统一数据层、统一执行层、统一知识层，持续稳定地做因子研究、沉淀经验、复用经验。
