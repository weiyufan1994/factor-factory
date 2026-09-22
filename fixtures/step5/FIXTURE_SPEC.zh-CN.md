> [English Version](FIXTURE_SPEC.md)

# Step 5 fixture 规范

## 目的
提供最小化的提交输入包，使 Bernard/Mac 能够在不依赖私有运行时输出的情况下执行 Step 5 闭环逻辑。

## 当前提交的 fixture 束
- `factor_run_master__sample.json`
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step5__sample.json`
- `factor_run_diagnostics__sample.json`
- `evaluation_payload__sample.json`
- `factor_values__sample.csv`
- `run_metadata__sample.json`

## 为什么该 fixture 有意是部分状态的
该极简样本继承了真实的 Step 4 部分 handoff。这是刻意设计的：Step 5 应证明对部分状态而非虚假的已验证/全窗口完成度的诚实闭环。

## 可接受的 fixture 形式
- 合成的但模式真实的 JSON
- 极简 csv/parquet 运行输出
- 极简评估载荷
- 小到可以安全提交

## 不可接受作为 fixture
- 从 EC2 复制完整归档树并称为 fixture 设计
- 当极简真实闭环样本足够时使用完整私有运行时输出束

## 成功标准关联
该 fixture 必须足以支撑 `scripts/run_step5_sample.sh` 中的 sample 命令，生成 `docs/contracts/step5-contract.md` 中描述的 Step 5 输出产物类集合。