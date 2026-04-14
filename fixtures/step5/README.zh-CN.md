> [English Version](README.md)

# Step 5 fixtures

## 当前提交的 fixture 集
- `factor_run_master__sample.json`
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step5__sample.json`
- `factor_run_diagnostics__sample.json`
- `evaluation_payload__sample.json`
- `factor_values__sample.csv`
- `run_metadata__sample.json`

## 目的
这些文件为 Bernard/Mac 提供了第一套极简提交的 Step 5 可复现性底层。

## 当前 runner
- `scripts/run_step5_sample.sh`
- `scripts/run_step5_sample.py`

## 重要边界
该样本按构造有意为部分状态，设计为证明对部分 Step 4 handoff 的真实 Step 5 闭环。