> [English Version](README.md)

# Step 1 fixtures

## 当前已提交的 fixture 集合
- `sample_factor_report.html`
- `sample_intake_response.json`

## 目的
这些文件提供了 Bernard/Mac 视角下 Step 1 第一版已提交的微型可复现基底。

## 当前覆盖的路径
- 本地 HTML ingestion 路径
- structured intake parsing 路径
- report_map / validation artifact 写出路径

## 当前 runner
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## 成功预期
一次成功的样本运行，应产出与以下类别等价的 Step 1 artifact：
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## 重要边界
这个 fixture 有意保持 tiny 且 schema-truthful；它不是为了代表完整的生产级研报复杂度。
