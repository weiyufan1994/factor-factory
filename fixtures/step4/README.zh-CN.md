> [English Version](README.md)

# Step 4 fixtures

## 当前提交的 fixture 集
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## 目的
这些文件为 Bernard/Mac 提供了第一套极简提交的 Step 4 可复现性底层。

## 当前 runner
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

## 重要边界
该样本按构造有意为部分窗口。它设计为产生真实的 `partial` Step 4 样本，而非虚假的 `success` 声明。