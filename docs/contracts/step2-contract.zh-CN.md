> [English Version](step2-contract.md)

# Step 2 合约

## 当前判断
Step 2 是 canonical spec 闸门。它消费批准的 Step 1 intake 产出的 `alpha_idea_master`，并产出 `factor_spec_master`、`handoff_to_step3` 与 Step3B 所需研究上下文。

## 机制数学合约
`factor_spec_master` 携带 `mechanism_math_contract`，版本为 `factorforge_mechanism_math_contract_v1`。这是 operator、direct_code、hybrid 共用的增量研究层。`specified` 合约必须包含模型家族、数学工具箱、经济机制、状态/对象、可观测输入、estimator 映射、target functional、单调性声明、信息集、预期指标签名、revision operators、falsification tests 与 kill criteria。如果机制不能负责任地数学化，Step2 写 `math_model_status=under_specified`，并给出 `under_specified_reason` 与 `next_human_research_question`。

## 当前提交的可复现性输入
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

## runner 状态
sample/debug runner 对 canonical 写入已 archived 或 debug-blocked。正式 Step2 必须使用批准的 producer contract，不能用手写 JSON 取代。

## 输入类
- `alpha_idea_master__{report_id}.json`
- 主 alpha thesis 产物
- 挑战者 alpha thesis 产物
- 主 report_map 产物
- `source_type`：只能是 `pdf_report`、`paper_canonical_formula`、`natural_language_hypothesis`
- 被批准的 producer metadata

`pdf_report` 可以解析 report registry/PDF 上下文。`paper_canonical_formula` 与 `natural_language_hypothesis` 不要求本地 PDF。

## 输出类
- `factor_spec_master__{report_id}.json`
- 主 raw spec 产物
- 挑战者 raw spec 产物
- 一致性审计产物
- Step 3 handoff 产物

`factor_spec_master` 与 `handoff_to_step3` 都必须包含：
- `contract_version = factorforge_step2_source_contract_v2`
- `source_type`
- `producer`
- `upstream_producer`
- `implementation_mode = operator | direct_code | hybrid`
- `spec_hash`
- `artifact_identity`
- `research_contract`
- `math_discipline_review`
- `learning_and_innovation`

`artifact_identity` 必须包含 `report_id`、`factor_id`、`source_type`、`implementation_mode`、`contract_version`、`producer`、`upstream_producer`、`spec_hash`、`branch_id`、`artifact_role`。operator mode 必须有 `formula_hash`；direct-code mode 必须有 `code_hash` 或 `code_contract_hash`；hybrid mode 必须有 `formula_hash` 与 `custom_block_hash`。

## Operator 公式合约

当 `implementation_mode=operator` 时，Step2 必须把 `formula_text` 解析成 `factorforge_formula_ir_v1` 的 `formula_ir`。spec 必须包含 `formula_hash`、`operator_set`、`required_fields`、`resolved_fields`、`field_aliases` 与 `parse_status`。`paper_canonical_formula` 来源必须有成功的 Formula IR。未知算子、语法错误、负窗口、未来函数、字段 alias 缺失都必须 BLOCK。

qlib expression bridge 必须显式记录 supported/unsupported，不能把 unsupported qlib operator 静默替换成近似表达式。Step3B 的 operator codegen 以 pandas reference evaluator 作为 parity oracle。

当公式引用 Alpha101 标准语义字段 `volume`、`returns`、`vwap` 或
`advN` 时，Step2 必须写入 `standard_formula_fields_contract` 及 hash，并
在 `factor_spec_master`、`canonical_spec`、`handoff_to_step3` 三处保持一致。
合同必须记录 source candidates、derivation rules、lookback policy 和
leakage policy。缺字段来源、缺 leakage policy 或只写“derive if needed”
必须 BLOCK。

## Hybrid 合约

`implementation_mode=hybrid` 必须使用 `factorforge_hybrid_contract_v1`。合约必须包含带 Formula IR 的 `operator_subgraph`、非空 `custom_blocks`、boundary schema，以及 `formula_hash`、`custom_block_hash`、`hybrid_hash`。字段缺失或 hash 不一致必须 `BLOCK_INVALID_HYBRID_CONTRACT`。

custom block 必须声明 function name、input/output schema、required fields、forbidden patterns 和 source code。operator output 默认受保护；除非 boundary 显式允许，否则 custom code 不能覆盖 operator output。

## 研究合约字段

Step 2 是 canonical spec 的第一道闸门。`factor_spec_master` 必须包含：
- `thesis.alpha_thesis`
- `thesis.target_prediction`
- `thesis.economic_mechanism`
- `math_discipline_review.step1_random_object`
- `math_discipline_review.target_statistic`
- `math_discipline_review.information_set_legality`
- `math_discipline_review.expected_failure_modes`
- `learning_and_innovation.similar_case_lessons_imported`
- `learning_and_innovation.innovative_idea_seeds`
- `learning_and_innovation.reuse_instruction_for_future_agents`

Step 3 handoff 必须继续携带 `research_contract`、`math_discipline_review` 与 `learning_and_innovation`。

Step3B 必须从这些字段构造 `step2_research_context`，并拒绝 missing sentinel。

## producer 闸门
允许的 Step2 producer：
- `step2_pdf_report`
- `step12_canonical_formula_intake`
- `step12_hypothesis_intake`

source 与 producer 严格一一对应：
- `pdf_report` -> `step2_pdf_report`
- `paper_canonical_formula` -> `step12_canonical_formula_intake`
- `natural_language_hypothesis` -> `step12_hypothesis_intake`

以下字段的 producer 必须非空且在 allowlist：`factor_spec_master.producer`、`factor_spec_master.upstream_producer`、`factor_spec_master.research_contract.producer`、`handoff_to_step3.producer`、`handoff_to_step3.research_contract.producer`。任何包含 `manual`、`debug`、`fake`、`posthoc`、`unknown`、`adhoc`、`ad_hoc` 的 producer 字符串，一律阻断正式 Step3。

## 当前代码层位置
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor-forge-step2/**`

## 可复现性警告
Step 2 的极小复现目前依赖将 fixture 对象拷贝至 runner 期望的对象路径，因为现有 Step 2 runner 围绕该对象合约构建。
