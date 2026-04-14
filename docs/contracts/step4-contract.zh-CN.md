> [English Version](step4-contract.md)

# Step 4 合约

## 当前判断
Step 4 目前已有第一套极简提交的可复现性底层设计，以真实的部分窗口样本为核心。

## 当前提交的可复现性输入
- `fixtures/step4/factor_spec_master__sample.json`
- `fixtures/step4/data_prep_master__sample.json`
- `fixtures/step4/handoff_to_step4__sample.json`
- `fixtures/step4/minute_input__sample.csv`
- `fixtures/step4/daily_input__sample.csv`
- `fixtures/step4/factor_impl__sample.py`

## 当前提交的 sample runner
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

## 输入类
- factor spec
- data prep master
- handoff_to_step4
- 极简本地分钟/日线输入
- 可运行的实现文件

## 输出类
- `factor_run_master__{report_id}.json`
- `factor_run_diagnostics__{report_id}.json`
- `runs/{report_id}/` 下的样本运行输出
- 评估载荷（evaluation payload）
- `handoff_to_step5__{report_id}.json`

## 可复现性警告
该极简 fixture 有意设计为部分窗口样本。它证明的是真实的 Step 4 部分执行，而非假装全窗口成功。