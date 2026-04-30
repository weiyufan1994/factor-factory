> [English Version](step2-contract.md)

# Step 2 合约

## 当前判断
Step 2 目前已有第一套极简提交的可复现性底层设计，但仍比 Step 1 更依赖上游产物。

## 当前提交的可复现性输入
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

## 当前提交的 sample runner
- `scripts/run_step2_sample.sh`
- `scripts/run_step2_sample.py`

## 输入类
- `alpha_idea_master__{report_id}.json`
- 主 alpha thesis 产物
- 挑战者 alpha thesis 产物
- 主 report_map 产物
- 足够支撑当前 runner 运行的状态解析底层

## 输出类
- `factor_spec_master__{report_id}.json`
- 主 raw spec 产物
- 挑战者 raw spec 产物
- 一致性审计产物
- Step 3 handoff 产物

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

## 当前代码层位置
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor-forge-step2/**`

## 可复现性警告
Step 2 的极小复现目前依赖将 fixture 对象拷贝至 runner 期望的对象路径，因为现有 Step 2 runner 围绕该对象合约构建。
