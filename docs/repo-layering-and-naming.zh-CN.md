> [English Version](repo-layering-and-naming.md)

# 仓库分层与命名原则

## 目的

本文用于解释：在阅读本仓库时，如何避免把以下几个层次混为一谈：
- 历史上的 Step 1 优先建设过程；
- 当前 Step1–Step5 的最小可复现范围；
- 工程实现层；
- 运行产物层。

## 分层原则

### A. Reader-first 治理层
这是新读者应该最先接触的层。

- `README.md`
- `docs/contracts/`
- `docs/reproducibility/`
- `docs/closeouts/`

这一层负责定义：仓库**声称自己是什么**，以及**当前到底能复现到什么程度**。

### B. 微型可复现层
这是提交进 git、可最小运行的样本层。

- `fixtures/step1/` 到 `fixtures/step5/`
- `scripts/run_step1_sample.sh` 到 `scripts/run_step5_sample.sh`
- `scripts/run_step1_sample.py` 到 `scripts/run_step5_sample.py`

这一层存在的目的，是避免仓库只能依赖隐藏本地状态或聊天上下文才能被理解和运行。

### C. 工程实现层
这是实际代码实现所在的层。

- `skills/factor_forge_step1/modules/`
- `skills/factor_forge_step1/prompts/`
- `skills/factor_forge_step1/schemas/`
- `skills/`

这一层可以保留历史构建顺序带来的偏斜，因此它目前仍然会显得比其他步骤更偏向 Step 1。
但这种偏斜不应被误读为仓库整体身份。

### D. 运行产物层
这是本地运行后生成内容累积的地方。

- `objects/`
- `runs/`
- `archive/`
- `evaluations/`
- `generated_code/`

这些路径在操作上很重要，但不应决定仓库对人的顶层表达。

## 命名原则

### 1. 文档命名
- 契约文档：`docs/contracts/stepN-contract.md`
- 可复现说明：`docs/reproducibility/*`
- 验收 / 收口说明：`docs/closeouts/*`

### 2. Fixture 命名
- 已提交的微型样本文件应放在 `fixtures/stepN/`
- 对 canonical 微型样本对象，优先使用 `__sample` 后缀

示例：
- `alpha_idea_master__sample.json`
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`

### 3. 运行对象命名
运行对象应显式写出对象类别，并保留 handoff 的方向信息。

示例：
- `alpha_idea_master__{report_id}.json`
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- `factor_run_master__{report_id}.json`
- `factor_case_master__{report_id}.json`
- `handoff_to_step3__{report_id}.json`
- `handoff_to_step4__{report_id}.json`
- `handoff_to_step5__{report_id}.json`

### 4. 脚本命名
微型样本运行入口应保持显式、带步骤编号。

- `run_step1_sample.py|sh`
- `run_step2_sample.py|sh`
- `run_step3_sample.py|sh`
- `run_step4_sample.py|sh`
- `run_step5_sample.py|sh`

### 5. 术语范围原则
以下术语应统一使用：

- **minimal reproducibility chain** —— 指 Step1–Step5 已提交的微型样本可复现链路
- **engineering layer** —— 指位于 `skills/` 下的步骤实现层，如 step-specific modules / prompts / schemas 以及 skill wrappers
- **runtime layer** —— 指运行过程中生成的 objects / runs / archives / evaluations
- **truthful partial sample** —— 指有意保持 partial 状态、而非伪造成成功的真实样本

应避免以下混淆：
- 把 fixture 样本包装成生产级证明；
- 把 runtime artifact 路径误当成仓库架构本身；
- 把早期 Step 1 优先建设顺序误当成当前整个仓库的身份。

## 当前治理规则

在未来若无明确批准的大规模迁移前，当前仓库治理应优先：
- 提升根目录可读性；
- 提升分层边界清晰度；
- 提升命名一致性；

而不是先做大规模目录迁移。

这就是当前仓库的清理治理口径。
