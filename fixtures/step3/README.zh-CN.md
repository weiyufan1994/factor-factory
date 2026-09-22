> [English Version](README.md)

# Step 3 fixtures

## 当前提交的 fixture 集
- `factor_spec_master__sample.json`
- `alpha_idea_master__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## 目的
这些文件为 Bernard/Mac 提供了第一套极简提交的 Step 3 可复现性底层。

## 当前 runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## 重要边界
Step 3 是第一个其极简 fixture 必须包含小规模表格本地输入的模块，因为当前验证器需要真实的 `local_input_paths`，且 Step 3B 在本地快照存在时必须发出首次因子值。