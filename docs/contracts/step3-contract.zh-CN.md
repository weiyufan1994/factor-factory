> [English Version](step3-contract.md)

# Step 3 合约

## 当前判断
Step 3 现在以独立 Data API 为边界。Step3A 解析 catalog contract 并产出 Step4 data contract；Step3B 在存在 sample query 时只能产出非正式样本执行证明。

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
- Step3A 产出的 Data API sample query
- 可运行的实现文件，供 Step 3B 做样本可执行性证明

## 输出类
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- 生成/可编辑的代码产物
- Step3B 非正式样本因子值输出
- `handoff_to_step4__{report_id}.json`

## Step3B / Step4 边界
Step3B 只负责用 Step3A 的 Data API sample contract 生成非正式 `step3b_sample_factor_values`，证明代码和 schema 可运行。Step3B 不应执行 Step4 职责：
- 不生成 IC 报告；
- 不生成 quantile NAV；
- 不生成组合图表；
- 不做 portfolio / backend evaluation。
- 不做 full-data fetch；
- 不写正式 `factor_values__{report_id}` 或 `run_metadata__{report_id}`。

这些统一由 Step4 标准评估器和执行层负责。Step4 消费 `step4_data_contract`，通过 `factorforge_data_api` 拉取全量数据，并拥有正式 factor values。

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
Step4 handoff、生成代码审查注释，以及样本运行 metadata（如果生成）。该上下文至少保留
target statistic、economic mechanism、expected failure modes、reuse instructions 和
implementation invariants，让 Step4/5/6 评价的是被实现的研究假设，而不是孤立的数值列。

## 实现与因子身份隔离
正式 Step3B 必须消费带 `manifest_identity` 与显式路径的 runtime manifest。必须拒绝路径猜测、按 mtime 选最新文件、跨 report 或跨 factor 复用。`artifact_identity` 链必须从 `factor_spec_master` 到 `implementation_plan_master`、generated code metadata、`handoff_to_step4` 在 `report_id`、`factor_id`、`source_type`、`implementation_mode`、`contract_version`、`spec_hash`、`branch_id` 上一致。

允许的 implementation mode 只有 `operator`、`direct_code`、`hybrid`。mode 不一致、stale `spec_hash`、branch 错误、复制其他 factor 的 generated code、或缺失 manifest identity，都属于 contract failure。

## Implementation mode 决策审计
Step3B 必须把 `implementation_mode_decision` 写入 `implementation_plan_master`、generated-code metadata、`handoff_to_step4`、样本运行 metadata（如生成），以及 ultimate proof summary。决策记录必须使用 `factorforge_implementation_mode_decision_v1`，明确 selected mode 或 `blocked`，记录 operator/hybrid/direct_code 的尝试结果或 not-applicable 原因，并保留最终 correctness reason。如果 selected mode 是 `blocked`，Step3B 不得写样本输出或正式 factor values。

## 正确性优先于完成度
Step3B 必须按 `operator -> hybrid -> direct_code` 尝试；如果无法证明正确性，就 BLOCK。UBL/CPV/shadow/candle/Williams 逻辑只能作为显式 family plugin 或 fixture。unsupported operator parity、缺失 `formula_ir`、不安全 direct code、或模糊 proxy 改写都必须 BLOCK，不能降级为 warning。

## Operator / Qlib engine
Operator mode 是 Formula IR 执行路径，不只是一个标签。Step3B 必须消费 `formula_ir`，验证 `parse_status=success`，确认所有算子在 registry 中，按 Step3A schema 解析字段 alias，生成 pandas `compute_factor`，并用 pandas reference evaluator 做 parity validation。生成 metadata 必须包含 `implementation_source=formula_ir_pandas_codegen`、`formula_hash`、`operator_set`、`required_fields`、`resolved_fields`、`code_hash` 和 qlib bridge status。

qlib expression bridge 必须显式声明 supported 或 unsupported。unsupported qlib operator 不能被近似替代。parser failure、unsupported operator、字段 alias 缺失、code hash 不一致或 parity failure 都必须 BLOCK，且不得生成正式 factor values。

## Hybrid execution engine
Hybrid mode 是有边界的组合：Formula IR operator subgraph 加上声明过的 custom Python block。Step3B 必须用 pandas reference parity 验证 operator subgraph，用 direct-code 泄漏规则扫描 custom source，校验 `formula_hash`、`custom_block_hash`、`hybrid_hash`，并在写 ready artifact 前验证 boundary。

生成的 hybrid code 必须用 `FACTORFORGE_OPERATOR_SUBGRAPH` 和 `FACTORFORGE_CUSTOM_BLOCK` markers 分隔 operator 和 custom 区域。除非 `allow_operator_output_overwrite=true`，custom block 不得覆盖受保护的 operator output；unsafe 或 unsupported hybrid contract 必须 BLOCK。

## Direct-code 与 custom-block 性能策略
Step3B 必须为 `direct_code` 实现和 hybrid custom block 生成 `factorforge_high_speed_code_profile_v1`。生成代码应优先使用向量化 NumPy 和/或 Polars；pandas 向量化 API 可作为兼容层或 reference 层。Python row loop、`DataFrame.apply(axis=1)`、`groupby.apply`、`rolling.apply` 属于慢模式风险，必须在对应 code contract 或 custom block 中写明 `allow_slow_patterns=true` 和非空 performance justification。未说明理由的慢模式必须在 fixture smoke 或 ready artifact 写入前 BLOCK。

## Family plugin 边界
UBL、CPV、shadow candlestick、candle、Williams 等 family-specific 代码必须放在 `factor_factory.factor_families` registry 后面。Step3B 只有在 Step2 显式声明 `factor_family`、`family_plugin`、`family_plugin_allowed=true`，并写出带非 free-text 证据的 `factorforge_family_plugin_decision_v1` 时才能执行 plugin。`factor_id`、公式文本、thesis 关键词最多只能产生人工复核建议，不能触发 plugin。

## 可复现性警告
Step 3 的极小复现目前依赖一个薄封装层，将 fixture 文件安装到 runner 期望的对象和本地输入路径，因为现有 Step 3 脚本围绕该对象合约构建。
