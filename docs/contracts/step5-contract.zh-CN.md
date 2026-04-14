> [English Version](step5-contract.md)

# Step 5 合约

## 当前判断
Step 5 目前已有第一套极简提交的可复现性底层设计，以真实的部分状态闭环样本为核心。

## 当前提交的可复现性输入
- `fixtures/step5/factor_run_master__sample.json`
- `fixtures/step5/factor_spec_master__sample.json`
- `fixtures/step5/data_prep_master__sample.json`
- `fixtures/step5/handoff_to_step5__sample.json`
- `fixtures/step5/factor_run_diagnostics__sample.json`
- `fixtures/step5/evaluation_payload__sample.json`
- `fixtures/step5/factor_values__sample.csv`
- `fixtures/step5/run_metadata__sample.json`

## 当前提交的 sample runner
- `scripts/run_step5_sample.sh`
- `scripts/run_step5_sample.py`

## 输入类
- factor_run_master
- factor_spec_master
- data_prep_master
- handoff_to_step5
- 极简评估载荷
- 支撑归档/案例闭环所需的极简运行输出

## 输出类
- `factor_case_master__{report_id}.json`
- `factor_evaluation__{report_id}.json`
- `archive/{report_id}/` 下的归档包

## 可复现性警告
该极简 fixture 有意设计为部分状态闭环样本。它证明的是真实的 Step 5 闭环，而非假装经过验证/全窗口成功。