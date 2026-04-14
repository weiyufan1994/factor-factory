> [English Version](step1-step5-minimal-reproducibility-acceptance-2026-04-14.md)

# 2026-04-14 —— Step1–Step5 最小可复现链路验收说明

- 仓库：`factorforge`
- 范围：`FactorForge Step1–Step5 Bernard/Mac 最小可复现链路`
- 验收时间：2026-04-14 07:26 UTC
- 验收状态：`pass`（最小可复现级别）

## 最终结论

截至本说明出具时，仓库已经从：
- 仅“skill 可见 / code 可见”

升级为：
- **仓库内存在 Step1–Step5 的最小可复现链路**

这**不意味着**完整生产级复现已经完成。
但它**意味着**：从 Step 1 到 Step 5，每一步现在都已具备：
1. 已提交的 fixture 层；
2. 已提交的 sample runner；
3. 本地可运行的样本证据；
4. GitHub 已推送留痕。

因此，正确的验收措辞应为：

> **FactorForge Step1–Step5 minimal reproducibility chain 已在 tiny-fixture / Bernard-Mac-ready-first-version 层级通过验收。**

## 已完成内容

### 仓库结构与治理层
仓库现已显式具备以下可复现结构：
- `docs/reproducibility/`
- `docs/contracts/`
- `docs/closeouts/`
- `fixtures/step1/` 到 `fixtures/step5/`
- `scripts/run_step1_sample.sh` 到 `scripts/run_step5_sample.sh`
- `scripts/run_step1_sample.py` 到 `scripts/run_step5_sample.py`

这意味着 source / skill / reproducibility / fixture 等层次已经能够在仓库中被显式区分，足以支持 Bernard/Mac 视角的最小复现。

### Step 1
#### fixture 层已存在
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

#### sample runner 已存在
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

#### 证据
本地样本运行已产出与 Step 1 对应的 artifact 类别：
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

#### GitHub 留痕提交
- `e8d72d4` — `fixtures: add runnable step1 tiny reproducibility sample`

### Step 2
#### fixture 层已存在
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

#### sample runner 已存在
- `scripts/run_step2_sample.sh`
- `scripts/run_step2_sample.py`

#### 证据
本地样本运行已完成并写出 Step 2 对应 artifact 类别：
- primary raw spec artifact
- challenger raw spec artifact
- consistency audit artifact
- `factor_spec_master`
- `handoff_to_step3`

#### GitHub 留痕提交
- `408a23e` — `fixtures: add runnable step2 tiny reproducibility sample`

### Step 3
#### fixture 层已存在
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

#### sample runner 已存在
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

#### 证据
Step 3 本地样本运行已产出：
- `data_prep_master`
- `qlib_adapter_config`
- `implementation_plan_master`
- generated code artifacts
- `handoff_to_step4`
- 首轮 factor-value 输出

校验器证据：
- `validate_step3.py --report-id STEP3_SAMPLE_CPV` → `RESULT: PASS`
- `validate_step3b.py --report-id STEP3_SAMPLE_CPV` → `RESULT: PASS`

#### GitHub 留痕提交
- `1b3c514` — `fixtures: add runnable step3 tiny reproducibility sample`

### Step 4
#### fixture 层已存在
- `fixtures/step4/factor_spec_master__sample.json`
- `fixtures/step4/data_prep_master__sample.json`
- `fixtures/step4/handoff_to_step4__sample.json`
- `fixtures/step4/minute_input__sample.csv`
- `fixtures/step4/daily_input__sample.csv`
- `fixtures/step4/factor_impl__sample.py`

#### sample runner 已存在
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

#### 证据
Step 4 本地样本运行已产出：
- `factor_run_master`
- `factor_run_diagnostics`
- evaluation payload
- run metadata
- `handoff_to_step5`
- validation revision artifact

校验器证据：
- `validate_step4.py --report-id STEP4_SAMPLE_CPV` → `RESULT: PASS`
- `VALIDATED_RUN_STATUS: partial`

这是**有意保持真实 partial** 的样本，而不是伪造成功样本。

#### GitHub 留痕提交
- `35c1ea2` — `fixtures: add runnable step4 tiny partial sample`

### Step 5
#### fixture 层已存在
- `fixtures/step5/factor_run_master__sample.json`
- `fixtures/step5/factor_spec_master__sample.json`
- `fixtures/step5/data_prep_master__sample.json`
- `fixtures/step5/handoff_to_step5__sample.json`
- `fixtures/step5/factor_run_diagnostics__sample.json`
- `fixtures/step5/evaluation_payload__sample.json`
- `fixtures/step5/factor_values__sample.csv`
- `fixtures/step5/run_metadata__sample.json`

#### sample runner 已存在
- `scripts/run_step5_sample.sh`
- `scripts/run_step5_sample.py`

#### 证据
Step 5 本地样本运行已产出：
- `factor_evaluation`
- `factor_case_master`
- 非空 archive bundle

校验器证据：
- `validate_step5.py --report-id STEP5_SAMPLE_CPV` → `result: PASS`
- 所列检查均返回 `ok: true`

这同样是**有意保持真实 partial-status closure** 的样本。

## 验收边界

本次验收意味着：
- Bernard/Mac 现在拥有 Step1–Step5 每一步的已提交 tiny sample 路径；
- 每一步现在都具备 in-repo contracts + reproducibility notes + fixture layer + sample runner；
- 仓库不再只能依赖聊天记录或隐藏本地状态，来解释 Step1–Step5 应如何以最小规模运行。

本次验收**不意味着**：
- Mac 上的生产级全量复现已解决；
- 所有环境/运行时依赖都已做到一键打包；
- 当前 sample runners 已经是最终 clean-room 架构。

## 最终判断

当前仓库满足的正确第一版验收说法是：

> **Step1–Step5 minimal reproducibility chain accepted.**
> **Bernard/Mac 已拥有每一步真实存在于仓库中的 tiny-fixture 路径、可运行样本入口与 GitHub 留痕。**
