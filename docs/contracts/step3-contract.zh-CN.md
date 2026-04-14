> [English Version](step3-contract.md)

# Step 3 合约

## 当前判断
Step 3 目前已有第一套极简提交的可复现性底层设计，但比 Step 1/2 要求更高，因为当前验证需要本地输入快照，且 Step 3B 在存在快照时必须发出首次运行输出。

## 当前提交的可复现性输入
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

## 当前提交的 sample runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## 输入类
- `factor_spec_master__{report_id}.json`
- `alpha_idea_master__{report_id}.json`
- 极简本地分钟/日线样本输入
- 可运行的实现文件，供 Step 3B 首次生成输出

## 输出类
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- 生成/可编辑的代码产物
- 首次运行因子值输出
- `handoff_to_step4__{report_id}.json`

## 可复现性警告
Step 3 的极小复现目前依赖一个薄封装层，将 fixture 文件安装到 runner 期望的对象和本地输入路径，因为现有 Step 3 脚本围绕该对象合约构建。