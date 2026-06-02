# Factor Forge Production Contract Closeout 2026-06-03

本文件记录长期 production contract 收口后的操作口径。它不是 Alpha036 或
Alpha037 个案补丁。

## 硬合同链路

1. Step2 写 `standard_formula_fields_contract`。
2. Step3A 消费该合同，写 report-local `derived_field_contract`，且不修改 clean data。
3. Step3B 只写 sample-only executability proof，不拥有 formal factor values。
4. Step4 拥有 formal factor values，写 `acceptance_summary` 和 qlib taxonomy。
5. Step6 写 `evidence_status`，拆分 wrapper/self-quant/qlib/research decision。
6. Dirac-style research report 必须说明 formula-implied latent information、metric
   anomaly、model-linked metric signature、volatility drag、drawdown recovery area。
7. Composite formula Council packet 必须包含 component-level ablation 和方向丢失审查。

## 禁止口径

- 不得说 qlib partial success。
- 不得说 Step3B formal factor values。
- 不得说 partial run without layer。
- 不得把 raw formula restatement as mechanism。
- 不得把 generic stochastic process as explanation。

## 关键 BLOCK token

- `BLOCK_STANDARD_FORMULA_FIELDS_MISSING`
- `BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING`
- `BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING`
- `BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS`
- `BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING`
- `BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT`
- `BLOCK_ACCEPTANCE_SUMMARY_MISSING`
- `BLOCK_ACCEPTANCE_SUMMARY_RUN_IDENTITY_MISSING`
- `BLOCK_ACCEPTANCE_SUMMARY_BACKEND_SPLIT_MISSING`
- `BLOCK_ACCEPTANCE_SUMMARY_REUSE_STATUS_MISSING`
- `BLOCK_ACCEPTANCE_SUMMARY_SIDE_EFFECTS_MISSING`
- `BLOCK_QLIB_PARTIAL_LABELED_SUCCESS`
- `BLOCK_QLIB_SAMPLE_STUB_NATIVE_SUCCESS`
- `BLOCK_QLIB_PARTIAL_MANDATORY`
- `BLOCK_STEP6_EVIDENCE_STATUS_MISSING`
- `BLOCK_DIRAC_FORMULA_IMPLIED_INFORMATION_MISSING`
- `BLOCK_COUNCIL_COMPONENT_ABLATION_MISSING`

## 生产边界

本收口不启动 worker，不跑生产 Step3B/Step4，不修改 raw data、clean data、Alpha036
或 Alpha037 artifacts。安装 skill sync 需在 reviewer 接受 repo-side changes 后执行。
