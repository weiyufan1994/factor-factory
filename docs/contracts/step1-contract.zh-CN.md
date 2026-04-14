> [English Version](step1-contract.md)

# Step 1 契约

## 输入类别
一个经过规范化的研报来源，由 Step 1 ingestion pipeline 消费。

## 当前已提交的可复现输入
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## 当前已提交的 sample runner
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## 输出类别
一次成功的 Step 1 样本运行，应产出与以下类别等价的 artifact：
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## 工程依赖层
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill 包装层
- `skills/factor-forge-step1*`

## 可复现警告
这个 tiny fixture 证明的是 Bernard/Mac 视角下 Step 1 artifact-class flow 已可最小复现；它并不意味着完整生产级研报复杂度已经被复现。
