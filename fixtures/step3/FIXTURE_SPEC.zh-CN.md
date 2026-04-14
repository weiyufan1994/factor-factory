> [English Version](FIXTURE_SPEC.md)

# Step 3 fixture 规范

## 目的
提供最小化的提交输入包，使 Bernard/Mac 能够在不依赖私有运行时状态或巨型数据载荷的情况下执行 Step 3A/3B。

## 当前提交的 fixture 束
- `factor_spec_master__sample.json`
- `alpha_idea_master__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## 为什么该束比 Step 1/2 更重
当前 Step 3 验证器需要真实的本地输入快照，而 Step 3B 在存在快照时必须发出首次运行输出。
因此诚实的 Step 3 极简 fixture 必须同时包含对象输入和小规模表格本地输入。

## 可接受的 fixture 形式
- 合成的但模式真实的 JSON
- 极简 csv 本地输入
- 极简可运行实现文件
- 小到可以安全提交

## 不可接受作为 fixture
- 巨型分钟/日线快照
- 生产用 parquet 束
- 将运行时生成的输出改标为 fixture 输入

## 成功标准关联
该 fixture 必须足以支撑 `scripts/run_step3_sample.sh` 中的 sample 命令，生成 `docs/contracts/step3-contract.md` 中描述的 Step 3 输出产物类集合。