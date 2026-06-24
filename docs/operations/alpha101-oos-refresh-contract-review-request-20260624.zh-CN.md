# Alpha101 OOS Refresh Contract Review Request

日期：2026-06-24

作者角色：Factor Forge Ultimate 二号 coder / 程序员2号

## Review 目的

请 review `/tmp/factorforge-alpha101-oos-refresh-contract` 分支中的 generic Alpha101 operator OOS refresh contract。

该合同是为了解决 Alpha015 当前正式阻塞：

```text
BLOCK_ALPHA101_GENERIC_OOS_FACTOR_VALUE_REFRESH_MISSING
```

目标不是直接证明 Alpha015 OOS 有效，而是补齐普通 Alpha101 Formula-IR/operator 因子的 OOS factor-value refresh 能力，使后续可以：

1. 保留 parent IS factor artifact；
2. 生成 window-scoped OOS factor values；
3. 产出 append compatibility proof；
4. 支持 batch checkpoint/resume；
5. 之后再 append/rebuild `factor_library_exposure_panel_v1` 并跑正式 OOS residual/model-combination proof。

## 分支状态

```text
worktree: /tmp/factorforge-alpha101-oos-refresh-contract
branch: codex/alpha101-oos-refresh-contract
review_scope_head_before_final_doc_fix: 6fe71c5 Update Alpha101 OOS refresh review request
contract_implementation_commit: 64c5be6 Harden Alpha101 OOS refresh resume identity
status: clean
```

说明：本 review request 自身可能继续产生 doc-only commit，因此不要把
`branch_HEAD` 当成 runner 代码的审查锚点。实际代码合同审查锚点是
`contract_implementation_commit=64c5be6`；后续 doc-only commit 只用于修正
review 口径。

相关 commits：

```text
54797fc Add Alpha101 OOS refresh contract prototype
c1b15c7 Document Alpha101 OOS refresh cold-cache boundary
4add795 Add Alpha101 OOS refresh batch checkpointing
94b24a2 Harden Alpha101 OOS refresh batch manifest
205c4da Add Alpha101 OOS refresh review request
0dc611f Update Alpha101 OOS refresh review handoff
c104e95 Harden Alpha101 OOS refresh label guard
ca99a76 Prove Alpha101 OOS refresh batch resume
64c5be6 Harden Alpha101 OOS refresh resume identity
6fe71c5 Update Alpha101 OOS refresh review request
```

## 改动范围

新增/修改：

```text
scripts/run_alpha101_operator_oos_refresh.py
scripts/run_alpha101_operator_oos_refresh_smoke.py
scripts/run_alpha101_operator_oos_refresh_batch.py
scripts/run_alpha101_operator_oos_refresh_batch_smoke.py
docs/operations/alpha101-oos-refresh-contract-20260624.zh-CN.md
docs/operations/alpha101-oos-refresh-contract-review-request-20260624.zh-CN.md
```

## 合同语义

### Single-window refresh

`run_alpha101_operator_oos_refresh.py` 输入：

- `source_report_id`
- `factor_id`
- original Formula-IR formula
- target OOS window
- `clean_daily_bar_oos_slice`
- optional universe/history window

输出：

```text
runs/<source_report_id>/oos_refresh/<start>_<end>/
  factor_values__<source_report_id>__oos_<start>_<end>.parquet
  run_metadata__<source_report_id>__oos_<start>_<end>.json
  factor_library_append_compatibility__<source_report_id>__oos_<start>_<end>.json
```

必须保持：

- `source_report_id` 不变；
- formula hash 可追溯；
- `revision_fitting_allowed=false`；
- `same_report_id_parent_factor_parquet_overwrite=false`；
- factor values 无 future return label；
- duplicate key count 为 0；
- append compatibility proof 为 `ACCEPT`。

### Batch checkpoint refresh

`run_alpha101_operator_oos_refresh_batch.py` 按 calendar month 拆分 target OOS window，并在每个 batch 后写 manifest。

Manifest 必须包含：

```text
version: factorforge_alpha101_operator_oos_refresh_batch_v1
batch_execution_plan.version: factorforge_batch_execution_plan_v1
refresh_policy.checkpoint_resume_supported: true
refresh_policy.append_outputs_are_batch_partitioned: true
```

这满足 Factor Forge Ultimate 的 bounded batch execution protocol，用于避免 full OOS 单次无界长跑。

## 验证已跑

```text
python3 -m py_compile \
  scripts/run_alpha101_operator_oos_refresh.py \
  scripts/run_alpha101_operator_oos_refresh_smoke.py \
  scripts/run_alpha101_operator_oos_refresh_batch.py \
  scripts/run_alpha101_operator_oos_refresh_batch_smoke.py

python3 scripts/run_alpha101_operator_oos_refresh_smoke.py
python3 scripts/run_alpha101_operator_oos_refresh_batch_smoke.py
git diff --check
```

验证结果：

```text
single-window smoke: ACCEPT
batch smoke: ACCEPT
batch smoke window: 20250731-20250801
batch_count: 2
completed_batch_count: 2
failed_batch_count: 0
row_count: 4
date_count_sum: 2
batch_execution_plan.version: factorforge_batch_execution_plan_v1
wall_seconds: about 20s on Mac cold cache
```

历史观察：

```text
longer cold-cache smoke window: 20250714-20250801
wall_seconds: about 132s
interpretation: Data API S3 parquet partition hydration dominates cold-cache runtime.
```

## 研究员复核补充

2026-06-24 复核时重新运行：

```text
python3 -m py_compile ...
python3 scripts/run_alpha101_operator_oos_refresh_smoke.py
python3 scripts/run_alpha101_operator_oos_refresh_batch_smoke.py
git diff --check
```

结果仍为：

```text
single-window smoke: ACCEPT
batch smoke: ACCEPT
batch smoke window: 20250731-20250801
batch_count: 2
completed_batch_count: 2
failed_batch_count: 0
row_count: 4
date_count_sum: 2
batch_execution_plan.version: factorforge_batch_execution_plan_v1
```

另用 Alpha015 当前 best branch 公式做 2 ticker / 2 target dates 的贴近真实公式小样本复核：

```text
formula: (((-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7)) * rank(amount)) * (0.40 + (0.60 * (1 - rank(turnover)))))
target: 20250714-20250715
history_start: 20250601
universe: 000001.SZ,000002.SZ
```

该复核在 Mac sandbox 中超过 4 分钟未完成后被人工中断。中断栈仍停在
Data API `aws s3 cp` 分区下载路径，而不是 Formula-IR parser/evaluator：

```text
factorforge_data_api/backends/s3_file.py
_download_s3_parquet_to_path(...)
aws s3 cp ...
```

解读：当前合同的单窗口/批量行为 smoke 通过，但 Alpha015 真实公式 full OOS
仍应在 true worker + persistent warm cache 上跑，或者先由 Data API/worker
预热 `clean_daily_bar_oos_slice` 分区。Mac cold cache 不是 full OOS 性能证明。

2026-06-24 继续硬化：

- `run_alpha101_operator_oos_refresh.py` 现在对 forbidden label columns 直接 BLOCK；
- 覆盖列包括 `future_return*`、`next_return`、`target_return`、`future_*`、`lookahead`、精确 `label`、精确 `target`；
- compatibility proof 继续输出 `contains_future_return_label`，并新增 `contains_forbidden_label_columns` 与 `forbidden_label_columns`；
- `run_alpha101_operator_oos_refresh_smoke.py` 增加负例 detector check。
- `run_alpha101_operator_oos_refresh_batch_smoke.py` 现在同一 workspace 连续跑两次 batch refresh：
  - 第一次生成两个 calendar-month batch；
  - 第二次用 `--resume` 重跑；
  - 第二次必须返回两个 `reused_existing_batch`，且 `row_count` / `date_count_sum` 与第一次一致。
- `run_alpha101_operator_oos_refresh_batch.py` 现在对 resume 命中做 identity 校验，不再只看文件存在：
  - 校验 `source_report_id`、`factor_id`、`formula`、`dataset_id`、batch window、`universe_request`；
  - 如果命令请求与已有 batch 元数据不一致，返回 `BLOCK_OOS_REFRESH_BATCH_RESUME_IDENTITY_MISMATCH`；
  - batch smoke 增加负例：同路径把公式从 `rank(close)` 改成 `rank(open)` 后用 `--resume`，必须 BLOCK，不能复用旧 batch。

复跑：

```text
py_compile: PASS
single-window smoke: ACCEPT
batch smoke: ACCEPT
batch resume reuse proof: ACCEPT
batch resume identity mismatch blocker: ACCEPT
git diff --check: PASS
```

## Review 重点问题

请重点判断：

1. `runs/<source_report_id>/oos_refresh/<start>_<end>/` 是否是可接受的 window-scoped output path，能否避免覆盖 parent IS `factor_values__<source_report_id>.parquet`？
2. `factor_library_append_compatibility__*.json` 的字段是否足够作为后续 exposure panel append/rebuild 的输入证明？
3. `batch_execution_plan` 是否满足 Factor Forge Ultimate bounded batch execution protocol？
4. `history_start` / lookback overlap 口径是否足够：runner 未显式传入时会从 Formula-IR lookback 做保守 calendar-day buffer，显式传入时按调用方 contract 执行。
5. 是否应把这两个 runner 集成进正式 Step4 / Ultimate wrapper，还是保留为受控 framework utility，由 wrapper 显式调用？
6. 如果用于 Alpha015 full OOS，是否必须在 true research worker + persistent warm `FACTORFORGE_DATA_CACHE` 上运行，而不是 Mac cold cache？
7. 是否需要新增 blocker：
   - `BLOCK_ALPHA101_OOS_REFRESH_PARENT_OVERWRITE_RISK`
   - `BLOCK_ALPHA101_OOS_REFRESH_APPEND_COMPAT_INVALID`
   - `BLOCK_ALPHA101_OOS_REFRESH_BATCH_PLAN_MISSING`
   - `BLOCK_OOS_REFRESH_BATCH_RESUME_IDENTITY_MISMATCH`

## 明确边界

本分支没有做：

- Alpha015 full OOS 正式研究；
- worker production run；
- Step3B/Step4/Step5/Step6 official wrapper run；
- factor library exposure panel append/rebuild；
- official promotion；
- clean data 修改；
- search worker；
- OOS formula fitting 或参数搜索。

因此 review 通过只能说明 OOS refresh 合同可以进入可审集成/worker execution 阶段，不能说明 Alpha015 OOS 通过。

## 建议 reviewer verdict

如果上述合同和验证足够，请给：

```text
ACCEPT_FOR_ALPHA101_OOS_REFRESH_INTEGRATION
```

如果还需要改，请按 P0/P1/P2 给出明确 blockers。P0/P1 未关闭前，研究员不应把该 prototype 产物当作 formal Alpha015 OOS proof。
