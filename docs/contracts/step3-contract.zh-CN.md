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
- 可选 `handoff_to_step3__{report_id}.json`
- Step2 研究字段：`thesis`、`research_contract`、`math_discipline_review`、`learning_and_innovation`
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

## Step3B / Step4 边界
Step3B 只负责生成或执行首次 `factor_values`，证明代码和输入快照可运行。Step3B 不应执行 Step4 职责：
- 不生成 IC 报告；
- 不生成 quantile NAV；
- 不生成组合图表；
- 不做 portfolio / backend evaluation。

这些统一由 Step4 标准评估器负责。若 Step3B 因分位数计算、回测图表或 portfolio 逻辑超时，应视为流程边界错误，而不是因子实现本身失败。

## 日期键标准
Step3A / Step3B / Step4 的 `trade_date` 边界必须兼容：
- `YYYYMMDD` 字符串；
- `YYYYMMDD` 整数；
- `YYYY-MM-DD` 字符串；
- pandas Timestamp。

但 Step4 消费时必须通过 `factor_factory.data_access.normalize_trade_date_series()` 统一归一化，不允许每个因子脚本自行解析并形成不同口径。

## Step 2 研究上下文传递
Step 3B 直接消费 Step2 的 factor spec 和 handoff。它必须把一致的
`step2_research_context` 写入 implementation plan、qlib expression draft、hybrid scaffold、
Step4 handoff、生成代码审查注释，以及首跑 metadata（如果生成）。该上下文至少保留
target statistic、economic mechanism、expected failure modes、reuse instructions 和
implementation invariants，让 Step4/5/6 评价的是被实现的研究假设，而不是孤立的数值列。

## 可复现性警告
Step 3 的极小复现目前依赖一个薄封装层，将 fixture 文件安装到 runner 期望的对象和本地输入路径，因为现有 Step 3 脚本围绕该对象合约构建。
