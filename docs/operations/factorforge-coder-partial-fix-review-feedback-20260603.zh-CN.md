# Factor Forge 长期生产合同修复复核反馈

日期：2026-06-03

复核角色：因子研究员 / Factor Forge Ultimate 使用方

复核对象：coder 声称已修复的 Factor Forge 长期问题，包括 Step1/2 机制建模、Step3A/Step3B 边界、Step4 performance/reuse/qlib 证据、Step6 evidence status 与生产验收输出。

## 结论

本轮不能判定为全部修好，只能判定为 **部分修复**。

已经有实质进展的部分：

1. Dirac-style / formula-implied mechanism 层已经有实装和 validator。
2. Step3A blocked 时 Step3B 不再能硬升级为 executable，边界变得更严格。
3. Step3A 能在 report-local snapshot 中派生 `volume / returns / vwap / advN`，并声明不污染 clean data。
4. Step3B/Step4 performance/reuse smoke 在 `/tmp` 合成路径通过，未污染 canonical artifacts。

仍未闭合的核心生产合同：

1. `standard_formula_fields_contract` 仍未进入 Step2/Step3A/validator 的统一正式链路。
2. performance profile 仍缺顶层 production `acceptance_summary`。
3. qlib 仍缺稳定的 `qlib_native_status` taxonomy。
4. Step4 formal run master 仍缺统一顶层 `run_id / artifact_root / producer / verdict` 等验收字段。
5. Step6 仍未拆分 `wrapper_validation_status / self_quant_evidence_status / qlib_native_status / research_decision`。

因此，本轮应反馈为：

> 部分接受，不可宣称长期问题已解决。需要继续补生产合同和对应 smokes。

## 复核命令与结果

### 1. 语法检查

命令：

```bash
python3 -m py_compile \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_performance_smoke.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/qlib_backtest_adapter.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py
```

结果：PASS。

### 2. Mechanism Math v2 smoke

命令：

```bash
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

结果：

```json
{
  "verdict": "ACCEPT",
  "canonical_pollution": false,
  "summary_path": "/private/tmp/factorforge_mechanism_math_v2_smoke/mechanism_math_v2_smoke_summary.json"
}
```

判断：Dirac-style `formula_implied_information` / `formula_implied_information_review` 合同已经有实装和验证。

### 3. Performance smoke

命令：

```bash
python3 scripts/run_factorforge_performance_smoke.py
```

结果：

```json
{
  "verdict": "ACCEPT",
  "canonical_pollution": {
    "polluted": false,
    "new_files": []
  },
  "notes": [
    "Synthetic /tmp-only smoke.",
    "No real factor research was run.",
    "No clean data was read or processed."
  ]
}
```

summary path：

```text
/tmp/factorforge_performance_20260603_102621/performance_smoke_summary.json
```

判断：performance/reuse/Step4 本地合成路径没有坏，且没有 canonical pollution。但该 smoke 并不覆盖全部长期生产验收合同。

## 已解决或明显改善

### 1. Step3A blocked -> Step3B hard block

当前 `run_step3b.py` 已有硬阻断：

```text
BLOCK_STEP3B_REQUIRES_READY_STEP3A
```

意义：

1. Step3A 不能准备可执行数据时，Step3B 不能伪造 executable path。
2. 避免坏 handoff 继续污染 Step4/Step5/Step6。
3. 符合“formal artifacts 坏了就 BLOCK，而不是让 worker compute 背锅”的目标。

这是实质修复。

### 2. Step3A report-local derived fields

当前 Step3A 能在 report-local daily snapshot 中派生：

```text
volume
returns
vwap
advN
```

并在 contract 中记录：

```json
{
  "report_local_only": true,
  "clean_data_mutation": false
}
```

意义：

1. 对 Alpha101 常见字段别名有实际处理。
2. 不再要求 clean data 本身被污染性改写。
3. Step3A 作为 Data API consumer 的边界基本保持正确。

但这还不是完整的 `standard_formula_fields_contract`，见下文未解决部分。

### 3. Dirac-style mechanism contract

当前 mechanism_math v2 validator 已要求：

```text
formula_implied_information
formula_implied_information_review
```

并且能 block raw-field restatement。

意义：

1. 机制建模不再只是复述公式字段。
2. 已开始接近我们讨论的“公式倒逼信息”思路。
3. 对 Step1/2 机制研究有正向支撑。

但该层目前更像 mechanism_math 子系统合同，还没有完全变成 Step1/2/6 全链路生产报告验收的统一出口。

## 未解决问题

### P0. `standard_formula_fields_contract` 仍缺正式闭环

当前检索结果显示，`standard_formula_fields_contract` 主要存在于 docs/plans/feedback 中，没有进入正式生产代码。

现状：

1. Step3A 有 `derived_field_contract`。
2. Step2 没有稳定输出 `standard_formula_fields_contract`。
3. Step3 validator 没有校验标准字段合同。
4. Step4 没有把该合同作为 formal factor execution 的输入证明。

为什么不够：

`derived_field_contract` 只能证明 Step3A 临时派生了某些字段，但不能回答：

1. Step2 公式到底声明需要哪些 canonical fields？
2. 每个字段的单位、lookback、信息集、leakage 风险是什么？
3. Step3A 派生规则是否完全覆盖 Step2 声明？
4. Step4 正式计算是否消费了同一份字段合同？

建议：

新增或补齐：

```json
{
  "standard_formula_fields_contract": {
    "version": "factorforge_standard_formula_fields_contract_v1",
    "report_id": "<REPORT_ID>",
    "canonical_formula": "...",
    "required_fields": [],
    "field_derivations": [],
    "unit_contract": {},
    "lookback_contract": {},
    "information_set_contract": {},
    "leakage_risk_contract": {},
    "clean_data_mutation_allowed": false
  }
}
```

并增加 smoke cases：

```text
missing_standard_formula_fields_contract_blocks
missing_required_field_derivation_blocks
unit_contract_missing_blocks
lookback_or_information_set_missing_blocks
valid_standard_formula_fields_contract_passes
```

### P0. production `acceptance_summary` 仍缺失

当前 `scripts/run_factorforge_performance_profile.py` 输出的是：

```text
step3b_performance_profile
step3b_csv_output_profile
formula_engine_profile
self_quant_performance_profile
wrapper_command_timing
artifact_sizes
step4_formal_artifact_sizes
```

但没有顶层：

```text
acceptance_summary
```

现在 `acceptance_summary` 只出现在 `run_factorforge_acceptance_smoke.py` 的 smoke summary 文件名，不是生产验收结构。

为什么不够：

研究员做 production acceptance 时，仍然必须人工拼：

1. wrapper proof；
2. Step3B metadata；
3. Step4 formal metadata；
4. self_quant payload；
5. qlib payload；
6. performance profile；
7. side-effect proof。

这容易造成 Alpha036 这种问题：局部 PASS 被误读成整体 production PASS。

建议：

`run_factorforge_performance_profile.py --write-report` 应写出：

```json
{
  "acceptance_summary": {
    "version": "factorforge_production_acceptance_summary_v1",
    "report_id": "...",
    "repo_sha": "...",
    "run_id": "...",
    "artifact_root": "...",
    "wrapper_status": "PASS|BLOCK|FAILED",
    "step3b_backend": "...",
    "step4_backend": "...",
    "reuse_status": {},
    "qlib_native_status": "...",
    "side_effects": {
      "clean_data_processed": false,
      "search_worker_used": false,
      "official_promotion_written": false,
      "generated_code_out_of_bounds": false
    },
    "validator_verdict": "PASS|BLOCK|FAILED"
  }
}
```

并增加 smoke cases：

```text
missing_acceptance_summary_blocks
acceptance_summary_missing_run_identity_blocks
acceptance_summary_missing_backend_split_blocks
acceptance_summary_missing_reuse_status_blocks
acceptance_summary_missing_side_effects_blocks
valid_acceptance_summary_passes
```

### P0. qlib status taxonomy 仍缺失

当前 qlib payload 仍使用：

```text
status=partial
mode=sample_stub
status=success
mode=native_minimal
status=skipped_native_missing_provider
```

这不是稳定的 production taxonomy。

为什么不够：

`partial` 可能表示：

1. qlib 没安装；
2. qlib provider 缺失；
3. qlib import 成功但 native runtime failed；
4. 只生成 grouped diagnostics；
5. native minimal 成功；
6. native full backtest 成功。

这些状态在研究判断中完全不同，不能压成 `partial/success`。

建议引入：

```text
qlib_native_status =
  not_attempted |
  preflight_blocked |
  preflight_ready |
  partial_payload |
  native_minimal_success |
  native_backtest_success |
  failed
```

并要求报告层只能在：

```text
native_minimal_success
native_backtest_success
```

时说 qlib native 成功。`partial_payload` 只能说 self_quant 完整、qlib 辅助证据不完整。

### P1. Step4 formal run master 缺统一顶层验收身份字段

当前 `factor_run_master` 有：

```text
report_id
factor_id
artifact_identity
run_status
implementation_path
output_paths
...
```

但缺少可直接用于验收汇报的顶层：

```text
run_id
artifact_root
producer
status
verdict
repo_sha
```

影响：

1. 研究员汇报仍要从多个 artifact 里拼 `run_id/artifact_root`。
2. wrapper proof 与 Step4 run master 的身份对齐不够直接。
3. 生产验收和审计难度仍偏高。

建议：

在 Step4 formal output 与 wrapper proof 中统一这些字段，不要只藏在 nested `artifact_identity`。

### P1. Step6 evidence status 仍未拆分

当前 Step6 逻辑仍类似：

```text
run_status == partial -> current run is still partial
qlib_backtest != success -> qlib backend is not yet consistently successful
```

问题：

1. wrapper 是否 PASS；
2. self_quant 是否完整；
3. qlib 是否只是 partial；
4. research decision 是否 reject/iterate/promote；

这些仍混在 narrative weakness 中。

建议：

Step6 输出必须包含：

```json
{
  "evidence_status": {
    "version": "factorforge_step6_evidence_status_v1",
    "wrapper_validation_status": "PASS|BLOCK|FAILED",
    "self_quant_evidence_status": "complete|partial|missing|failed",
    "qlib_native_status": "not_attempted|preflight_blocked|preflight_ready|partial_payload|native_minimal_success|native_backtest_success|failed",
    "long_side_evidence_status": "complete|partial|missing|failed",
    "research_decision": "promote|iterate|reject|needs_human_review"
  }
}
```

并增加：

```text
scripts/run_factorforge_step6_evidence_status_smoke.py
```

覆盖：

```text
missing_evidence_status_blocks
wrapper_pass_self_quant_complete_qlib_partial_passes_with_clear_warning
qlib_partial_cannot_be_reported_as_native_success
research_reject_distinct_from_wrapper_failure
```

## 对 coder 本轮工作的评价

这轮改动不是无效的，确实修了一些关键边界：

1. Step3A/Step3B readiness gate 是正确方向。
2. report-local derived fields 对 Alpha101 生产运行是必要补丁。
3. Step4 performance/reuse smoke 覆盖面比之前更强。
4. Dirac-style mechanism_math v2 已经有 validator 和 smoke。

但这轮还没有解决“长期问题”的根：

1. 合同词还没有进入正式 artifact schema。
2. validator 没有把这些合同变成 hard block。
3. production report 还不能一眼回答验收问题。
4. qlib partial/success 语义仍可能被误读。
5. Step6 仍可能把证据完整性问题和研究判断问题混在一起。

## 下一轮最小收口建议

建议 coder 不要继续扩性能功能，也不要继续写更多说明文档。下一轮只做合同闭环：

1. 实装 `standard_formula_fields_contract`。
2. 实装 `acceptance_summary`。
3. 实装 `qlib_native_status` taxonomy。
4. 实装 Step6 `evidence_status`。
5. 增加对应 smoke，并让 smoke 覆盖缺字段 BLOCK 与 valid PASS。

最小验收命令应至少包括：

```bash
python3 -m py_compile \
  scripts/run_factorforge_performance_profile.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py

python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_standard_formula_fields_contract_smoke.py
python3 scripts/run_factorforge_production_acceptance_summary_smoke.py
python3 scripts/run_factorforge_qlib_status_taxonomy_smoke.py
python3 scripts/run_factorforge_step6_evidence_status_smoke.py
```

如果新增 smoke 还不存在，则这本身就是未闭合证据。

## 最终判定

当前状态：

```text
verdict: PARTIAL
accepted_scope:
  - mechanism_math_v2 formula_implied_information
  - Step3A blocked handoff -> Step3B hard block
  - report-local derived fields
  - performance/reuse smoke stability
not_accepted_scope:
  - standard_formula_fields_contract
  - production acceptance_summary
  - qlib_native_status taxonomy
  - Step4 top-level run identity/verdict
  - Step6 evidence_status split
  - full production acceptance contract smoke coverage
```

给 coder 的一句话反馈：

> 这轮是有实质进展的 partial fix，但还不是长期生产合同 closeout。请不要把 smoke PASS 或文档说明当作 acceptance；下一轮必须把标准字段、production summary、qlib taxonomy、Step6 evidence split 变成正式 artifact + validator + smoke hard block。

## 归档状态更新

用户已确认本 review 结论可作为本轮 **PARTIAL closure** 的正式接受证据。

当前归档状态：

```text
GitHub branch: codex/factorforge-long-term-production-contract-closeout
GitHub accepted commit: 7fa34665e10ad68231702df38b4c5efcf1d987d1
EC2 runtime synced commit: 4aa02009c53cd988ad86146d4daa68e846290a84
closure_status: PARTIAL_ACCEPTED
accepted_scope: production acceptance_summary entered top-level performance profile and has smoke coverage
review_findings: no P0/P1/P2 findings for the accepted partial closure scope
boundary: does not equal real report Step3B/Step4 production proof
```

后续边界：

1. 如果继续推进真实研究链路，需要单独授权 Alpha037 或指定 report 的 Step3B/Step4 proof run。
2. 如果没有新的真实 proof run 授权，本轮代码/contract closure 可按 PARTIAL_ACCEPTED 归档。

## 归档验证更新

验证日期：2026-06-03

验证方式：

1. 当前本地工作树不是 closure branch，且存在 dirty/untracked 文件，因此未切换当前工作树。
2. 使用 `git fetch` 确认远端 branch。
3. 使用 detached `/tmp` worktree 验证 accepted commit：

```bash
git worktree add --detach /tmp/factorforge-closure-verify-7fa 7fa34665e10ad68231702df38b4c5efcf1d987d1
```

### GitHub branch / commit

已验证：

```text
origin/codex/factorforge-long-term-production-contract-closeout
  -> 7fa34665e10ad68231702df38b4c5efcf1d987d1

commit: 7fa34665e10ad68231702df38b4c5efcf1d987d1
parent: f4cb9544d700539691f2c2ec167ffcb2a5b5859c
message: Expose production acceptance summary in performance profile
```

`f4cb9544d700539691f2c2ec167ffcb2a5b5859c` 是更大的 production contract closeout commit；`7fa34665...` 在其上补了 performance profile 顶层暴露 `acceptance_summary`。

### 已验证 smoke

在 `/tmp/factorforge-closure-verify-7fa` detached worktree 中执行：

```bash
python3 -m py_compile \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_production_acceptance_summary_smoke.py \
  scripts/run_factorforge_production_acceptance_contract_smoke.py \
  scripts/run_factorforge_qlib_status_taxonomy_smoke.py \
  scripts/run_factorforge_step6_evidence_status_smoke.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py
```

结果：PASS。

执行并通过：

```bash
python3 scripts/run_factorforge_production_acceptance_summary_smoke.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
python3 scripts/run_factorforge_qlib_status_taxonomy_smoke.py
python3 scripts/run_factorforge_step6_evidence_status_smoke.py
python3 scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
python3 scripts/run_factorforge_derived_field_contract_smoke.py
python3 scripts/run_factorforge_formal_artifact_identity_smoke.py
python3 scripts/run_factorforge_dirac_research_report_contract_smoke.py
```

全部结果：`verdict=ACCEPT`。

### 代码层验证结果

已验证：

1. `run_step4.py` 构造并写入 `factorforge_production_acceptance_summary_v1`。
2. `run_factorforge_performance_profile.py` 将 `factor_run_master.acceptance_summary` 暴露到 profile 顶层。
3. `validate_step4.py` 会对缺失 `acceptance_summary`、缺 run identity、缺 backend split、缺 reuse status、缺 side-effect proof 进行 BLOCK。
4. qlib partial / sample_stub 不再允许被标记为 native success。
5. Step6 已有 `factorforge_step6_evidence_status_v1`，拆分 wrapper / self-quant / qlib / long-side / cost / drawdown / research decision。
6. Alpha101 standard field contract、derived field contract、formal artifact top-level identity、Dirac-style research report contract 均有 smoke 覆盖。

### 未能从本地仓库验证

未能验证：

```text
EC2 runtime synced commit: 4aa02009c53cd988ad86146d4daa68e846290a84
```

原因：

1. `git cat-file` 在当前本地 repo 中未找到该 object。
2. `git ls-remote origin` 未返回该 commit。
3. 该 commit 可能属于 EC2 runtime repo / runtime branch / 非当前 GitHub origin 的状态，需要 EC2 runtime proof 或对应仓库远端引用才能验证。

### 边界确认

已确认 closure 文档明确写明：

```text
本收口不启动 worker，不跑生产 Step3B/Step4，不修改 raw data、clean data、Alpha036 或 Alpha037 artifacts。
```

因此本轮验证结论是：

```text
GitHub code/contract closure at 7fa34665: VERIFIED
production acceptance_summary top-level profile exposure: VERIFIED
contract smokes: VERIFIED
no real report Step3B/Step4 proof: CONFIRMED BY SCOPE
EC2 runtime synced at 4aa02009: UNVERIFIED FROM THIS LOCAL REPO
```

## 本地/EC2 使用面完善更新

验证日期：2026-06-03

### 本地持久 production-contract worktree

由于当前主工作区：

```text
/Users/humphrey/projects/factor-factory
branch: codex/factorforge-step3-step4-data-api-mac
HEAD: 05ab074d442a0f39814a5084701d7729ccd18d94
status: dirty / untracked files present
```

它不是 accepted closure branch，且缺少若干新增 smoke 脚本，因此不应作为本轮 production contract proof run 入口。

为避免覆盖当前 dirty 工作区，已创建持久本地 worktree：

```text
path: /Users/humphrey/projects/factor-factory-production-contract-closeout
branch: codex/local-factorforge-production-contract-closeout
tracking: origin/codex/factorforge-long-term-production-contract-closeout
HEAD: 7fa34665e10ad68231702df38b4c5efcf1d987d1
status: clean
```

验证：

```bash
python3 -m py_compile \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_production_acceptance_summary_smoke.py \
  scripts/run_factorforge_production_acceptance_contract_smoke.py \
  scripts/run_factorforge_qlib_status_taxonomy_smoke.py \
  scripts/run_factorforge_step6_evidence_status_smoke.py \
  scripts/run_factorforge_alpha101_standard_field_contract_smoke.py \
  scripts/run_factorforge_derived_field_contract_smoke.py \
  scripts/run_factorforge_formal_artifact_identity_smoke.py \
  scripts/run_factorforge_dirac_research_report_contract_smoke.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py
```

结果：PASS。

本地 worktree smoke：

```text
run_factorforge_production_acceptance_summary_smoke.py: ACCEPT
run_factorforge_qlib_status_taxonomy_smoke.py: ACCEPT
run_factorforge_step6_evidence_status_smoke.py: ACCEPT
run_factorforge_alpha101_standard_field_contract_smoke.py: ACCEPT
run_factorforge_derived_field_contract_smoke.py: ACCEPT
run_factorforge_formal_artifact_identity_smoke.py: ACCEPT
run_factorforge_dirac_research_report_contract_smoke.py: ACCEPT
```

Installed skills 同步状态：

```text
/Users/humphrey/.codex/skills/factor-forge-step2: diff clean vs closure worktree
/Users/humphrey/.codex/skills/factor-forge-step3: diff clean vs closure worktree
/Users/humphrey/.codex/skills/factor-forge-step4: diff clean vs closure worktree
/Users/humphrey/.codex/skills/factor-forge-step6: diff clean vs closure worktree
/Users/humphrey/.codex/skills/factor-forge-ultimate: diff clean vs closure worktree
```

本地结论：

```text
local installed skills: VERIFIED
local production-contract worktree: VERIFIED
current default repo checkout /Users/humphrey/projects/factor-factory: NOT_PRODUCTION_CLOSURE_CHECKOUT
```

后续本地真实 proof run 若要使用本轮完善代码，应从：

```text
/Users/humphrey/projects/factor-factory-production-contract-closeout
```

执行正式入口，而不是从当前 dirty dev checkout 执行。

### EC2 runtime 复验

SSM discovery：

```text
command_id: 9ef39806-59ac-41cb-b41d-a365f2899ebc
status: Success
```

EC2 runtime：

```text
instance: i-01c0ceb9c04ae270e
host: openclaw-new
repo: /home/ubuntu/.openclaw/workspace/factor-factory-production-v2
branch: humphrey-ec2/factorforge-step3-step4-data-api-runtime
HEAD: 4aa02009c53cd988ad86146d4daa68e846290a84
```

EC2 installed skills 已包含：

```text
Step4 acceptance_summary / qlib_native_status
Step4 validate_acceptance_summary hard blocks
Step6 factorforge_step6_evidence_status_v1
Step6 evidence_status validator hard blocks
```

EC2 smoke-only proof：

```text
command_id: 8f9f9cbf-14f1-4630-bb77-1407735e74cf
status: Success
response_code: 0
```

覆盖：

```text
run_factorforge_production_acceptance_summary_smoke.py
run_factorforge_production_acceptance_contract_smoke.py
run_factorforge_qlib_status_taxonomy_smoke.py
run_factorforge_step6_evidence_status_smoke.py
run_factorforge_alpha101_standard_field_contract_smoke.py
run_factorforge_derived_field_contract_smoke.py
run_factorforge_formal_artifact_identity_smoke.py
run_factorforge_dirac_research_report_contract_smoke.py
```

EC2 已知 dirty file：

```text
M scripts/build_factorforge_runtime_context.py
```

该 diff 是 runtime_context 写入前增加 Step1/Step2 validator gate，属于 EC2 control-plane guard，不是 Step3B/Step4/Step6 production contract 核心。该 dirty 状态需要保留记录，但不影响本轮合同标准判断。

EC2 结论：

```text
EC2 production runtime: VERIFIED
EC2 installed skills: VERIFIED
EC2 contract smokes: VERIFIED
EC2 real report Step3B/Step4 proof: NOT_RUN_BY_SCOPE
```
