> [English Version](FIXTURE_SPEC.md)

# Step 4 fixture 规范

## 目的
提供最小化的提交输入包，使 Bernard/Mac 能够在不依赖巨型本地数据的情况下执行 Step 4 执行/诊断逻辑。

## 当前提交的 fixture 束
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## 为什么该 fixture 有意是部分的
极简本地样本仅覆盖两个交易日，而目标窗口跨度更大。
这是有意为之：它真实地证明了 `partial` 分支。

## 可接受的 fixture 形式
- 合成的但模式真实的 JSON
- 极简 csv 本地输入
- 极简可运行实现文件
- 小到可以安全提交

## 不可接受作为 fixture
- 巨型分钟 parquet 快照
- 私有 EC2 运行时输出冒充 fixture 输入
- 抹去真实部分窗口性质的假成功 fixture

## 成功标准关联
该 fixture 必须足以支撑 `scripts/run_step4_sample.sh` 中的 sample 命令，生成 `docs/contracts/step4-contract.md` 中描述的 Step 4 输出产物类集合。