> [English Version](step1-contract.md)

# Step 1 契约

## 输入类别
Step 1 是研究来源 intake 层，职责是把任何被批准的研究来源转成 `alpha_idea_master`。

允许的 `source_type`：
- `pdf_report`：本地 PDF/HTML/report registry 来源。
- `paper_canonical_formula`：论文或 canonical formula 来源，例如 Alpha101，需要 source metadata 与公式文本。
- `natural_language_hypothesis`：用户自然语言研究假设，必须先结构化，再进入 Step 2。

## 当前已提交的可复现输入
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## runner 状态
sample/debug runner 只能作为 archived 或 isolated debug helper。正式 Step1/2 intake 必须使用批准的 producer，不得手写下游 Step3 artifact。

## 输出类别
一次成功的 Step 1 样本运行，应产出与以下类别等价的 artifact：
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact
- 带研究纪律字段的 alpha_idea_master

`alpha_idea_master` 必须包含：
- `source_type`
- `producer`
- `contract_version`

## 研究纪律字段

Step 1 必须保留研报原始 thesis，同时补齐后续审查需要的结构：
- `research_discipline.step1_mathematical_object`
- `research_discipline.target_statistic_hint`
- `research_discipline.information_set_hint`
- `research_discipline.initial_return_source_hypothesis`
- `research_discipline.what_must_be_true`
- `research_discipline.what_would_break_it`
- `research_discipline.similar_case_lessons_imported`

为当前 Step2/5/6 提供 `math_discipline_review.mathematical_object` 与
`learning_and_innovation.similar_case_lessons_imported`。旧 artifact 的
`step1_random_object` 只作为兼容别名读取，不应在新研究中强制生成。

## producer 闸门
正式 Step2 只能消费批准 producer 的 Step1 输出。任何包含 `manual`、`debug`、`fake`、`posthoc`、`unknown`、`adhoc`、`ad_hoc` 的 producer 字符串，一律不得进入正式 Step3。

## 工程依赖层
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill 包装层
- `skills/factor-forge-step1*`

## 可复现警告
这个 tiny fixture 证明的是 Bernard/Mac 视角下 Step 1 artifact-class flow 已可最小复现；它并不意味着完整生产级研报复杂度已经被复现。
