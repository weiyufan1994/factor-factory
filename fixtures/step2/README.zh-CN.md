> [English Version](README.md)

# Step 2 fixtures

## 当前提交的 fixture 集
- `alpha_idea_master__sample.json`
- `report_map_validation__sample__alpha_thesis.json`
- `report_map_validation__sample__challenger_alpha_thesis.json`
- `report_map__sample__primary.json`
- `sample_report_stub.pdf`

## 目的
这些文件为 Bernard/Mac 提供了第一套极简提交的 Step 2 可复现性底层。

## 当前 runner
- `scripts/run_step2_sample.sh`
- `scripts/run_step2_sample.py`

## 重要边界
该 fixture 集存在的原因是当前 Step 2 runner 依赖一组上游 Step 1 产物，而非仅一个 alpha_idea_master 文件。