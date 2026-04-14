> [English Version](step1-repro-card.md)

# Step 1 可复现说明卡

## 当前判断
Step 1 已经成为仓库中第一个具备“已提交、可运行、可说明”的微型可复现基底的模块。

## 仓库中已存在的工程实现层
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## 仓库中已存在的 Skill 包装层
- `skills/factor-forge-step1.skill`
- `skills/factor-forge-step1/**`

## 仓库中已存在的稳定执行入口
主代码入口：
- `skills/factor_forge_step1/modules/report_ingestion/orchestration/run_step1.py`

最小已提交可复现 runner：
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## 当前已提交 fixture
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## 当前被实际覆盖的路径
这个可复现基底有意只覆盖最小且稳定的 Step 1 路径：
1. 本地 HTML 来源规范化
2. structured intake parsing
3. report_map 构建与 schema 校验
4. alpha_thesis 写出
5. ambiguity_review 写出

## 当前成功标准
一次 Step 1 样本运行，只有在产出与以下类别等价的 artifact 时才算合格：
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## 当前限制
这是一套 tiny 且 schema-truthful 的可复现基底，不是完整的生产级研报复现包。
它的设计目标，是证明 Bernard/Mac 可以在不依赖私有 runtime cache 或超大 PDF 的前提下，复现 Step 1 的 artifact-class flow。
