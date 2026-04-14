> [English Version](factorforge-reproducible-tree-and-push-table-2026-04-14.md)

# 2026-04-14 —— FactorFactory 可复现仓库树与 Step1–5 推送判定表

- 工作流：`FactorFactory 仓库结构化整理 + Bernard/Mac 可复现边界`
- 状态：`drafted`
- 目的：定义当目标是 **Bernard/Mac 可直接复现** 时，仓库应如何组织，而不是仅仅做到 skill 可读

## 1. 最终结论

当前仓库中已经包含大量对 Step1–5 有价值的材料，但它**尚未完全整理成一个清爽的可复现工程仓库**。

核心问题不是“所有代码都缺失”，而是**层次混杂**：
- engineering implementation layer
- runtime / generated artifacts layer
- skill packaging layer
- documentation / contracts layer

这些层对我们自己而言尚可理解，但对 Bernard-on-Mac 直接复现仍不够友好。

因此，正确的下一标准应是：

> 推出一个仓库树，使 Bernard 能清楚地区分：
> 1. 哪些是 source code；
> 2. 哪些是 skill packaging；
> 3. 哪些是 reproducible fixture input；
> 4. 哪些是 runtime output；
> 5. 哪些默认不应提交。

## 2. 推荐的结构化仓库树

```text
factorforge/
├── README.md
├── pyproject.toml / requirements.txt                # 运行环境声明（待补）
├── docs/
│   ├── architecture/
│   ├── contracts/
│   ├── reproducibility/
│   └── closeouts/
├── src/
│   └── factorforge/
│       ├── step1/
│       ├── step2/
│       ├── step3/
│       ├── step4/
│       ├── step5/
│       ├── common/
│       └── report_ingestion/
├── skills/factor_forge_step1/prompts/
├── skills/factor_forge_step1/schemas/
├── skills/
│   ├── factor-forge-step1.skill
│   ├── factor-forge-step1/
│   ├── factor-forge-step2.skill
│   ├── factor-forge-step2/
│   ├── factor-forge-step3.skill
│   ├── factor-forge-step3/
│   ├── factor-forge-step4.skill
│   ├── factor-forge-step4/
│   ├── factor-forge-step5/
│   └── factor_forge_step5/
├── fixtures/
│   ├── step1/
│   ├── step2/
│   ├── step3/
│   ├── step4/
│   └── step5/
├── scripts/
│   ├── run_step1_sample.sh
│   ├── run_step2_sample.sh
│   ├── run_step3_sample.sh
│   ├── run_step4_sample.sh
│   └── run_step5_sample.sh
├── outputs/                                         # 可选本地目录，通常 gitignore
├── archive/                                         # 除精挑 proof bundle 外通常 gitignore
├── runs/                                            # 除精挑 fixture 外通常 gitignore
├── evaluations/                                     # 除精挑 fixture 外通常 gitignore
├── objects/                                         # 除精挑 reproducibility fixture 外通常 gitignore
└── .gitignore
```

## 3. 各层应如何理解

### A. 工程实现层
这是复现意义上的真正 source of truth。
它应包括：
- 可复用 Python 模块
- orchestration logic
- validators
- adapters
- prompt loaders
- schema helpers
- step-specific source code

**当前状态**
- Step 1 在这方面最清晰，目前位于 `skills/factor_forge_step1/modules/report_ingestion/**`
- Step 2–5 的大量代码仍主要嵌在 `skills/factor-forge-step*/scripts` 与 `skills/factor-forge-step5/modules` 下

**建议方向**
- Step 1 工程代码可以暂留现状，但长期应迁入 `src/factorforge/step1/`（或共享的 `src/factorforge/report_ingestion/`）
- Step 2–5 工程代码应逐步从 skill-only placement 提升到 `src/factorforge/step2..step5/`
- skill 目录应成为 packaging / invocation wrapper，而不应成为核心工程逻辑唯一住所

### B. Skill 层
这是供 OpenClaw 发现与调用的层。
它应包括：
- `SKILL.md`
- `references/`
- 薄脚本包装层 `scripts/`
- 仅在必要时捆绑的 helper modules

**规则**
如果目标是 Bernard/Mac 可直接复现，那么 skill 层不应成为关键工程逻辑的唯一落点。

### C. Fixture 层
这是最小可复现基底。
它应包括：
- 微型 synthetic 或微型真实样本输入
- 文件小且稳定，可直接提交
- 足以让 Bernard 在不依赖大数据集的情况下跑通每一步

**当前状态**
- 这层此前并未完全正式化
- 它是当前最重要的缺口之一

### D. Runtime 输出层
包括：
- `runs/`
- `archive/`
- `evaluations/`
- `objects/`

**规则**
这些目录通常应 gitignore；只有经过挑选、作为 reproducibility 证明的 tiny curated fixtures / proof bundles 才适合提交。

## 4. 当前阶段的近端清理建议

在不先做巨大重构的前提下，仓库也可以先按以下原则变得更有结构：

### 当前应保留
- `skills/`
- `skills/factor_forge_step1/prompts/`
- `skills/factor_forge_step1/schemas/`
- `skills/factor_forge_step1/modules/report_ingestion/**`（Step 1 工程层）

### 应尽快补齐
- `docs/reproducibility/`
- `docs/contracts/`
- `fixtures/`
- `scripts/`（sample runs）

### 默认不应推送
- `runs/**`
- `evaluations/**`
- `archive/**`
- `objects/**`
- 大型 parquet / csv artifacts

## 5. Step1–5 推送判定表

### 图例
- `Y` = 应为 Bernard/Mac 可复现而推送
- `N` = 默认不应推送
- `P` = partial / 当前仍不足 / 虽已推送但不足以支持完整复现

| Step | Skill layer | Engineering code layer | Fixture / sample input | Runtime output needed in git? | Current reproducibility judgment |
|------|-------------|------------------------|------------------------|-------------------------------|----------------------------------|
| Step 1 | Y | Y | P | N | **最接近可复现级别**，但仍需显式 fixture + run docs |
| Step 2 | Y | P | N | N | **尚未达到可复现级别**；工程逻辑仍主要在 skill scripts |
| Step 3 | Y | P | N | N | **尚未达到可复现级别**；仍需 fixture 与更清晰的 engine/source 分层 |
| Step 4 | Y | P | N | N | **尚未达到可复现级别**；代码已存在，但依赖上游本地 objects/data |
| Step 5 | Y | P | N | N | **尚未达到可复现级别**；已有好代码，但复现仍依赖上游 handoff fixture |

## 6. 各步骤解释

### Step 1
#### 应推送什么
- skill package
- `skills/factor_forge_step1/modules/report_ingestion/**`
- prompts
- schemas
- 一个 tiny reproducibility fixture
- 一条清晰 run command

#### 为什么
Step 1 已经具备了相对完整的工程层，是后续步骤应对齐的模板。

#### 当前判断
**接近可复现级别，但尚未完全达到**，因为 fixture + environment/run instructions 直到最近才被正式化。

### Step 2
#### 应推送什么
- skill package
- 提升到 engineering layer 的核心 source code
- 一个表现 `alpha_idea_master` / Step 1 handoff 形状的微型输入 fixture
- 一条确定性的运行路径

#### 当前判断
**当前推送对 Bernard 直接复现仍然不足。**

### Step 3
#### 应推送什么
- skill package
- 从 skill-only scripts 提升出来的工程代码
- 针对 `factor_spec_master` / `data_prep_master` 形状的 tiny fixture
- 运行说明

#### 当前判断
**当前推送对 Bernard 直接复现仍然不足。**

### Step 4
#### 应推送什么
- skill package
- run / validate / adapters 的工程实现
- 微型受控本地输入 fixture，而不是超大 minute parquet
- 一条能在 Mac 上生成 tiny run artifact 的 sample command

#### 当前判断
**当前推送对 Bernard 直接复现仍然不足。**
主要缺口在 fixture / input 策略。

### Step 5
#### 应推送什么
- skill package
- run / validate / evaluator / case_builder / archiver / rules / io 的工程代码
- 一个来自 Step 4 的 tiny handoff fixture
- 一条确定性的 sample command

#### 当前判断
**当前推送对 Bernard 直接复现仍然不足。**
主要缺口在 fixture 与上游 object closure。

## 7. 各步骤的最小可复现标准

每一步最终都应满足以下五条：
1. 稳定工程层中存在 source code
2. skill package 作为 invocation wrapper 存在
3. tiny fixture 已提交
4. 文档中已有 sample run command
5. 文档中已有 success criterion

如果缺任何一条，就不应称之为 “Bernard/Mac directly reproducible”。

## 8. 仓库下一步具体动作

### 动作 1 —— tree regularization
在仓库中创建这些目录：
- `docs/reproducibility/`
- `docs/contracts/`
- `fixtures/`
- `scripts/`

### 动作 2 —— Step 1 正式可复现说明卡
编写：
- `docs/reproducibility/step1-repro-card.md`

应包含：
- 所需文件
- fixture 路径
- run command
- output expectation

### 动作 3 —— Step 2–5 gap cards
每一步一份：
- `docs/reproducibility/step2-gap-card.md`
- `docs/reproducibility/step3-gap-card.md`
- `docs/reproducibility/step4-gap-card.md`
- `docs/reproducibility/step5-gap-card.md`

每份都应明确写出：
- 仓库中已有什么
- 哪些仍只存在于 skill scripts
- 缺少什么 fixture
- Bernard direct reproduction 被什么卡住

### 动作 4 —— 不要把 runtime data 当成 reproducibility substitute
不要混淆：
- 巨大 minute parquet
- generated runs
- archived outputs

与：
- formal reproducibility fixtures

大型 runtime artifacts 是证据，但不是默认正确的可复现基底。

## 9. 最终判断

如果标准只是“OpenClaw 能发现这些 skills”，那么前面的 push 已经足够。
如果标准是“Bernard on Mac 能直接复现 Step1–5”，那么仓库仍然需要：
- 更清晰的树状分层
- Step2–5 工程代码提升
- 微型可提交 fixtures
- 显式 reproducibility docs

因此，当前状态的正确判断应是：

> **Step 1 = 接近可复现级别**  
> **Step 2–5 = code-visible 且 skill-visible，但尚未达到 Bernard/Mac 可直接复现级别**

## 10. 一句话总结
正确的推送目标不是“更多文件”，而是一个把 source code、skill wrappers、tiny fixtures 与 reproducibility docs 分清楚的仓库；只有这样 Bernard 才能在不依赖我们的私有 runtime outputs 的前提下跑通每一步。
