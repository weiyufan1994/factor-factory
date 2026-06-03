# Factor Forge Step4 Backtest Base 合同

本文定义 Step4 生产执行的 backtest base 边界。目标是把因子特异计算和可复用回测基座拆开，避免每个因子重复构建 label、mask、calendar、cost 大表。

## 生产规则

- formal factor values 的正式证据格式是 parquet。
- full factor CSV 默认禁用；缺省或 production 模式只能写 bounded sample CSV proof。
- `factor_values__<report_id>.csv` 只有在显式 debug/audit opt-in 下才允许写入，否则触发 `BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN`。
- `backtest_base_dataset_contract` 必须绑定 source data version、universe、calendar、label policy、tradable policy、cost policy 和 artifact hash。
- 已存在 base 只有在 identity 和 artifact hash 全匹配时才能复用。

## 必需字段

`backtest_base_dataset_contract` 至少包含：

- `version=factorforge_backtest_base_dataset_contract_v1`
- `backtest_base_dataset_id`
- `source_data_version`
- `clean_data_hash`
- `window_start`
- `window_end`
- `universe_id`
- `universe_hash`
- `label_policy`
- `tradable_policy`
- `cost_policy`
- `calendar_hash`
- `artifact_paths.labels`
- `artifact_paths.tradable_mask`
- `artifact_paths.calendar`
- `artifact_paths.cost_inputs`
- `artifact_hashes`
- `producer_step`
- `producer_repo_sha`
- `validator_verdict=PASS`

`factor_output_policy` 至少包含：

- `version=factorforge_factor_output_policy_v1`
- `formal_format=parquet`
- `full_factor_csv_written`
- `sample_csv_written`
- `full_csv_disabled_reason`
- `full_csv_non_default_opt_in`

`step4_phase_profile` 必须拆分：

- `factor_io`
- `backtest_base`
- `evaluation`
- `output`

## BLOCK token

- `BLOCK_BACKTEST_BASE_DATASET_MISSING`
- `BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH`
- `BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH`
- `BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH`
- `BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH`
- `BLOCK_BACKTEST_BASE_COST_POLICY_MISMATCH`
- `BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH`
- `BLOCK_STEP4_REUSE_GATE_AMBIGUOUS`
- `BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN`

## 复用语义

Step4 revision 只应重算 factor values。若 source data version、window、universe、label policy、tradable policy、cost policy 和 artifact hash 均一致，label/mask/calendar/cost base 必须复用。若任何字段缺失、矛盾或 artifact hash 不匹配，必须 BLOCK 或重建 base 并记录明确 reason，不允许 silent reuse。

`self_quant_analyzer` 和 `qlib_backtest` 应共用 `shared_evaluation_context` 中的 backtest-base reference，避免重复构建同一批 labels/masks/calendar/cost inputs。
