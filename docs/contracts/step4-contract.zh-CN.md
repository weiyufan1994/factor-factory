> [English Version](step4-contract.md)

# Step 4 合约

## 目的
Step 4 负责使用独立 `factorforge_data_api` 的声明窗口输入，或由这些输入生成且已审查的研究侧派生状态，执行已审查的因子，并产出 Step 5/6 可以审阅的标准评估证据。官方证据不得依赖临时截图、notebook 图、一次性脚本图。

## 输入
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `handoff_to_step4__{report_id}.json`
- Step 3B 生成的可运行因子实现
- 当没有 legacy local inputs 时，Step3A/Step3B handoff 中的 `step4_data_contract.version=factorforge_step4_data_contract_v1`
- 已发布的源 Data API catalog；local IS 也可按[研究侧派生输入契约](../../skills/factor-forge-step4/references/research-derived-inputs.md)消费显式准备、已审查的研究侧派生状态，不要求先把研究中间状态发布成共享数据产品

## 强制输出
- `factor_run_master__{report_id}.json`
- `factor_run_diagnostics__{report_id}.json`
- `handoff_to_step5__{report_id}.json`
- `factorforge/evaluations/{report_id}/` 下各 backend 的 `evaluation_payload.json`
- `runs/{report_id}/factor_values__{report_id}.parquet` 或 `.csv`
- `runs/{report_id}/run_metadata__{report_id}.json`

Step3B 的 `step3b_sample_factor_values__{report_id}` 只是样本可执行性证据，不是正式输入。Step4 必须基于 Step4 Data API full query contract 或已审查的全窗口 prepared-state controller 绑定计算正式 factor values；只有 metadata 能证明 parquet 已由 Step4 写出时才可复用。

## self-quant 强制证据包
`self_quant_analyzer` 必须输出以下全部标准 artifacts，Step 4 才能视为完整：

- `rank_ic_timeseries.png`
- `pearson_ic_timeseries.png`
- `coverage_by_day.png`
- `quantile_returns_10groups.csv`
- `quantile_nav_10groups.csv`
- `quantile_counts_10groups.csv`
- `quantile_summary_table.csv`
- `long_short_returns_10groups.csv`
- `long_short_nav_10groups.csv`
- `quantile_nav_10groups.png`
- `quantile_counts_10groups.png`
- `long_short_nav_10groups.png`

## 指标契约
`self_quant_analyzer` 必须在 payload 中写入 `standard_metric_contract`。阻断项包括 artifact 缺失、IC 非有限值、十分位收益/NAV 表畸形、分组为空、NAV 非正、NAV 首个观测点未归一到 1.0。

## 绘图纪律
临时绘图不得作为 Step 4 官方证据。需要新增图或表时，必须加入 backend artifact contract，由 `run_step4.py` 生成，并由 `validate_step4.py` 验证。

## 可复现性提示
极简 fixture 仍可用于 smoke test，但正式研究 case 必须产出上面的完整标准证据包。
