> [English Version](FIXTURE_SPEC.md)

# Step 2 fixture 规范

## 目的
提供最小化的提交输入包，使 Bernard/Mac 能够在不依赖隐藏运行时状态或巨型报告资产的情况下执行 Step 2。

## 当前提交的 fixture 束
- `alpha_idea_master__sample.json`
- `report_map_validation__sample__alpha_thesis.json`
- `report_map_validation__sample__challenger_alpha_thesis.json`
- `report_map__sample__primary.json`
- `sample_report_stub.pdf`

## 为什么该束比 Step 1 的更大
当前 Step 2 runner 消费的是真实的上游对象束，而非仅仅一个语义输入文件。
因此诚实的 Step 2 极简 fixture 必须反映该依赖表面。

## 必须保持真实的字段
- `report_id`
- 因子标识字段
- Step 2 逻辑所需的 assembly / thesis 字段
- 决策流中包含的未解决歧义

## 可接受的 fixture 形式
- 合成的但模式真实的 JSON
- 仅用于路径解析的极简本地存根
- 小到可以安全提交

## 不可接受作为 fixture
- 当极简替代品足够时使用完整研究报告 PDF
- 从本机复制的私有运行时缓存并称为 fixture
- 超出最低要求集合的巨型上游对象束
- 将 Step 2 的输出改标为输入

## 成功标准关联
该 fixture 必须足以支撑 `scripts/run_step2_sample.sh` 中的 sample 命令，生成 `docs/contracts/step2-contract.md` 中描述的 Step 2 输出产物类集合。