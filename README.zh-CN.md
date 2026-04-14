> [English Version](README.md)

# FactorForge

FactorForge 是一个 **Step1–Step5 因子研究流水线仓库**，并且已经具备一条提交入库的 **最小可复现链路（minimal reproducibility chain）**。

建议按以下顺序阅读本仓库：
1. **根 README** —— 说明仓库是什么、应如何入门；
2. **`docs/reproducibility/`** —— 说明当前最小可复现边界；
3. **`docs/contracts/`** —— 说明各步骤的输入/输出/运行契约；
4. **`fixtures/step*/` + `scripts/run_step*_sample.*`** —— 提供最小可运行样本路径；
5. **`skills/` / runtime object paths** —— 提供按步骤分布的工程实现层与运行产物层。

## 当前仓库判断

截至 2026-04-14，本仓库已经不应再被理解为“仅仅是一个 Step 1 工程目录”。
更准确的表述是：

> **这是一个覆盖 Step1–Step5、并已提交最小可复现链路的仓库；其中 Step 1 是最早落地的工程层，但不是整个仓库的身份定义。**

之所以要强调这一点，是因为仓库中部分早期根目录文件与历史提交仍然保留了 Step 1 优先建设时期的痕迹；但当前仓库意图已经超出那个起点。

## 当前已纳入范围的内容

当前已经在仓库内被接受的基线包括：
- Step 1 到 Step 5 均有已提交的 fixture 目录；
- Step 1 到 Step 5 均有已提交的 sample runner；
- 各步骤契约已记录在 `docs/contracts/`；
- 可复现说明、差距卡、验收/收口文档已记录在 `docs/reproducibility/` 与 `docs/closeouts/`。

这意味着仓库现在已经具备一条 **tiny-fixture / Bernard-Mac-ready 的第一版最小可复现路径**，覆盖整个 Step1–Step5 链路。

## 当前不作出的声明

本仓库**尚不声明**以下事项：
- 已达到生产级的一键完整复现；
- 已完成最终洁净的跨机器打包；
- 已完成所有历史层的最终架构纯化；
- Step 4 / Step 5 的样本已经是 full-window success。

其中部分样本是**有意保持真实 partial 状态**，而不是伪造成功样本。

## 仓库分层

### 1）契约与可复现层
如果你的目标是理解仓库或尝试复现，请优先看这一层。

- `docs/contracts/` —— 稳定的步骤契约
- `docs/reproducibility/` —— 可复现说明卡与差距卡
- `docs/closeouts/` —— 验收与收口说明
- `fixtures/step1/` … `fixtures/step5/` —— 已提交的微型样本输入
- `scripts/run_step1_sample.*` … `scripts/run_step5_sample.*` —— 样本运行入口

### 2）工程实现层
如果你的目标是查看流水线究竟如何实现，请看这一层。

- `skills/factor_forge_step1/modules/` —— 当前 Step 1 的工程实现基底
- `skills/factor_forge_step1/prompts/` —— Step 1 prompt 资源
- `skills/factor_forge_step1/schemas/` —— Step 1 schema 资源
- `skills/` —— 各步骤的 skill 包装与步骤入口

### 3）运行/产出层
如果你的目标是查看本地运行产物、handoff 对象、归档与评估结果，请看这一层。

- `objects/` —— object / handoff 产物
- `runs/` —— 本地运行输出
- `archive/` —— 收口归档包
- `evaluations/` —— 评估输出
- `generated_code/` —— 生成出的实现代码产物

## 当前命名原则

- **步骤契约** 放在 `docs/contracts/stepN-contract.md`
- **可复现说明** 放在 `docs/reproducibility/`
- **验收 / 收口说明** 放在 `docs/closeouts/`
- **已提交的微型样本输入** 放在 `fixtures/stepN/`
- **样本运行脚本** 放在 `scripts/run_stepN_sample.py|sh`
- **handoff 对象** 统一使用 `handoff_to_stepN__{report_id}.json`
- **master 对象** 使用显式后缀命名，例如 `alpha_idea_master__{report_id}.json`、`factor_spec_master__{report_id}.json`、`data_prep_master__{report_id}.json`、`factor_run_master__{report_id}.json`、`factor_case_master__{report_id}.json`

命名与分层的目标，是让读者能够明确区分：
- **docs 层**
- **fixtures 层**
- **engineering code 层**
- **runtime artifact 层**

而不必靠聊天记录、提交考古或隐含上下文来猜测仓库结构。

## 现在应如何理解 Step 1

Step 1 仍然非常重要，但它现在应被理解为：
- **最早实现出来的工程层**；
- 整个 Step1–Step5 流水线中的一个步骤。

它不应再被误解为整个仓库的总代名词。

历史上，部分根目录文件曾来自“先搭 Step 1”的早期阶段；但这个历史事实，不应再覆盖当前仓库的总架构意图。

## 推荐阅读路径

1. `docs/closeouts/step1-step5-minimal-reproducibility-acceptance-2026-04-14.md`
2. `docs/reproducibility/README.md`
3. `docs/contracts/README.md`
4. `docs/contracts/step1-contract.md` 到 `step5-contract.md`
5. `docs/plans/private-fund-grade-factor-factory-gap-roadmap-2026-04-14.zh-CN.md`
6. `fixtures/step*/README.md`
7. `scripts/run_step*_sample.sh`

## 运行说明补充

较早的 Step 1 工程说明里曾强调过专用本地运行时环境；这一点现在仍然是实现细节，而不是仓库顶层身份。

## 常用命令入口

典型的最小样本运行方式如下：

```bash
./scripts/run_step1_sample.sh
./scripts/run_step2_sample.sh
./scripts/run_step3_sample.sh
./scripts/run_step4_sample.sh
./scripts/run_step5_sample.sh
```

## 路线图文档

如果要查看从当前 CPV 样例最小链路继续走向私募级因子工厂的下一阶段建设路径，请见：
- `docs/plans/private-fund-grade-factor-factory-gap-roadmap-2026-04-14.zh-CN.md`

## 当前清理原则

本轮清理的原则是：**先把治理表达、分层边界与命名清晰化**。
在根目录叙事和阅读路径尚未清楚之前，不应轻易做大规模目录迁移或大架构改造。
