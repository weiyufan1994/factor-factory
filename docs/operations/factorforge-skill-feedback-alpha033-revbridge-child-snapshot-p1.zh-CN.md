# Factor Forge Ultimate Loop 反馈：Alpha033 revision bridge 仍缺 child-local daily snapshot

日期：2026-05-19

## 结论

本轮 fresh Alpha033 生产路径复测显示：Council/Step6 approved revision 已经可以 materialize 成 child 可执行包，且 child formula / formula hash 已经不同于 parent；但 child daily snapshot 复制合同在真实路径仍未生效，导致 child Step4 无法评估。

因此当前链路应视为 **BLOCK**，不能继续手工复制 daily snapshot 后伪装完整闭环通过。

## Fresh Report

- parent report id: `ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426`
- child report id: `ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003`
- loop report: `objects/runtime_context/ultimate_loop_report__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.json`
- parent wrapper proof: `objects/runtime_context/ultimate_run_report__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.json`
- child wrapper proof: `objects/runtime_context/ultimate_run_report__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.json`
- materialization proof: `objects/runtime_context/child_revision_materialization__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.json`

## 已通过的部分

### 1. Main-agent memo pause / validator / Council dispatch 正常

- 初次 loop 从 Step2 开始后停在 `awaiting_main_agent_mechanism_memo`。
- 写入 main-agent freeform memo 后，`validate_main_agent_mechanism_memo.py` 返回 `PASS`。
- 继续 Step6 + `--council-mode auto` 后停在 `awaiting_agent_results`。
- parent wrapper proof 中：
  - `revision_council.status = awaiting_agent_results`
  - `revision_council.effective_mode = agentic_dispatch_manifest`
  - `revision_council.deterministic_scaffold_used = false`

### 2. Agentic Council 结果真实收集并 finalize

5 个 agent result 均写入并通过 validator：

- `agent_symbolic_law_discovery`
- `agent_dimensional_scaling_critic`
- `agent_stochastic_process_modeler`
- `agent_microstructure_cost_analyst`
- `agent_statistical_falsification_agent`

`finalize_agentic_council_dispatch.py` 返回 `PASS`，并写入：

- `objects/research_iteration_master/revision_council/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/revision_council_summary__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.json`
- `objects/research_iteration_master/revision_council/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/council_derivation_appendix__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.json`

Council summary 的 `selection_source = agentic_results`。

### 3. Child executable revision spec 和 formula hash 已经正确变化

child executable revision spec:

`objects/research_iteration_master/executable_revision_spec__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.json`

关键字段：

```json
{
  "parent_formula": "rank(negate(signedpower(minus(1, divide(open, close)), 1)))",
  "child_formula": "rank(minus(divide(close, open), 1))",
  "parent_formula_hash": "7a14e1e5b1078f873373de5f5bc6caf8eb1647c0105c0d62ef6fab5c6d67b5ec",
  "child_formula_hash": "8a047c5421f75c038bcb85ac16d7767958c494386e09c3a78a2b03e6098f183b",
  "derivation_rule": "open_close_sign_orientation_challenge"
}
```

child `factor_spec_master` 也已写入 child formula/hash：

```json
{
  "formula_text": "rank(minus(divide(close, open), 1))",
  "formula_hash": "8a047c5421f75c038bcb85ac16d7767958c494386e09c3a78a2b03e6098f183b",
  "revision_identity": {
    "revision_identity_status": "changed",
    "revision_noop": false
  }
}
```

## BLOCK 证据

### 1. Materialization report 没有 child daily snapshot

materialization report 的 `materialized_artifacts` 包含：

- `executable_revision_spec`
- `alpha_idea_master`
- `factor_spec_master`
- `data_prep_master`
- `qlib_adapter_config`
- `handoff_to_step3`
- `handoff_to_step4`

但没有：

- `child_daily_input_parquet`
- `child_daily_input_csv`

同时实际文件不存在：

```text
runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.parquet
runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.csv
```

parent daily snapshot 是存在的：

```text
runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.parquet
runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.csv
```

### 2. child data_prep_master 仍指向 parent daily path

child `data_prep_master` 的 `local_input_paths` 仍然是 parent 路径：

```json
{
  "daily_df_parquet": "factor-factory/runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.parquet",
  "daily_df_csv": "factor-factory/runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.csv",
  "preferred_daily_format": "parquet"
}
```

这说明 child-local copy rewrite 未发生。

### 3. child Step3B 实际也读取 parent daily snapshot

child `run_metadata` 的 `input_io_profile`：

```json
{
  "daily_selected_format": "parquet",
  "daily_selected_path": "/Users/humphrey/projects/factor-factory/runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426.parquet"
}
```

这违反了本轮要验证的合同：

> child Step3B should read child-local daily snapshot.

### 4. child Step4 按 child report-local 路径找输入并失败

child wrapper proof：

```json
{
  "status": "FAIL",
  "failure": {
    "command": "validate_step4",
    "returncode": 1
  }
}
```

Step4 stdout 中 self_quant_adapter 报错：

```text
FileNotFoundError: missing daily input:
/Users/humphrey/projects/factor-factory/runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.parquet
or
/Users/humphrey/projects/factor-factory/runs/ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003/step3a_local_inputs/daily_input__ALPHA033_CANONICAL_FORMULA_20160101_REVBRIDGE_RETEST_20260519_123426__LOOP01__MAIN_ITER_003.csv
```

Step4 validator 最终：

```json
{
  "verdict": "FAIL",
  "issues": [
    {
      "code": "BLOCK_NO_SUCCESSFUL_BACKEND"
    },
    {
      "code": "BLOCK_MISSING_SELF_QUANT_EVIDENCE"
    }
  ]
}
```

## 可能根因

`materialize_step6_child_revision.py` 的 `resolved_daily_sources()` 似乎没有解析 parent `data_prep_master.local_input_paths` 里的 repo-prefixed relative path：

```text
factor-factory/runs/<parent>/step3a_local_inputs/...
```

如果在 repo root `/Users/humphrey/projects/factor-factory` 下简单拼成：

```text
/Users/humphrey/projects/factor-factory/factor-factory/runs/...
```

就会误判 source 不存在，于是不会进入 copy child daily snapshot 的分支。Step3B 的 data access resolver 又能把它解析成真实 parent 路径，导致 Step3B 可以跑，但 Step4 按 child report-local 默认路径找不到输入。

这造成三层不一致：

1. materializer 没复制 child-local snapshot；
2. child data_prep 仍保留 parent daily path；
3. Step3B 读 parent daily，Step4 找 child daily。

## 建议修复

### P1：统一路径解析

`materialize_step6_child_revision.py` 不应自己实现一套弱 `resolved_path()`。建议复用 Step3B/Step4 当前正式 data access resolver，或至少支持：

- absolute path；
- repo-root relative path；
- `factor-factory/...` repo-name-prefixed relative path；
- 已存在的 legacy path 兼容。

### P1：child daily copy 必须是硬合同

当 parent data_prep 是 daily-only 且 parent daily snapshot 存在时，materializer 必须：

1. 复制 parquet 到 child report-local path；
2. 复制 csv 到 child report-local path，或明确按 audit policy 处理；
3. 重写 child `data_prep_master.local_input_paths.daily_df_parquet/csv` 为 child-local path；
4. materialization report 必须列出 `child_daily_input_parquet/csv`；
5. 如果无法复制，materializer 应 BLOCK，而不是继续创建一个 Step4 必失败的 child。

### P1：Step3B child 输入合同应强制验证

child Step3B 已强制读取 executable revision spec，但还需要验证：

- child report id 下的 `data_prep_master.local_input_paths` 不应指向 parent report id；
- `run_metadata.input_io_profile.daily_selected_path` 不应指向 parent report id；
- 如果 child Step3B 使用 parent daily snapshot 作为 optimization，必须同时保证 Step4 能消费同一路径，且 proof 明确说明这是 allowed alias；当前合同要求的是 child-local path，因此应 BLOCK。

### P2：materialization report 增加 explicit daily source diagnostics

建议在 materialization report 中写入：

```json
{
  "parent_daily_sources_detected": {...},
  "child_daily_targets_planned": {...},
  "child_daily_copy_status": "copied|blocked|not_required",
  "daily_source_resolution_warnings": [...]
}
```

这样下一次不用等到 Step4 才发现 daily copy 漏了。

## Side Effects

本轮失败前确认：

- no official promotion：parent/child official factor record 均不存在。
- materialization proof: `clean_data_touched = false`。
- parent Council finalize: `side_effects_unchanged = true`。
- 未运行 clean data processing。
- 未运行名为 `search_worker` 的命令。

注意：child Step3B 已按 loop 正常写入 child `generated_code/<child_report_id>/...` 和 child factor values，这是 child execution 的预期副产物，不是 parent formula 重跑污染；但由于 Step4 缺 daily snapshot，child metrics 不可用，不能比较 child metrics 是否不同。

## 当前研究判断

Alpha033 本轮不能继续给出完整 10-loop 研究结论。应该先修复 child daily snapshot materialization 合同，再 fresh rerun。当前可确认的进展只有：

1. main-agent memo / auto Council dispatch / real agent result / finalize 链路已通过；
2. parent -> child executable formula bridge 已通过，child formula hash 不再等于 parent；
3. child-local daily snapshot bridge 未通过，导致 Step4 evaluation BLOCK。

