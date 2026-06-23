# Alpha015 Step4 Sparse Formal Signal Framework Feedback

日期：2026-06-24

对象：Factor Forge 架构师 / Step4 validator coder

工作区：

`factor_research/Alpha015/alpha015_ultimate_promising_20260622`

## 结论

Alpha015 当前不是经济假设被证伪，而是 formal Step4 evidence contract 不够硬：

```text
BLOCK_FORMAL_FACTOR_SIGNAL_COVERAGE_MISMATCH
```

正式 Step4 产物拥有 full-window row count，但真正非空的 `factor_value` 只覆盖 47 个交易日。Ultimate wrapper 仍记录 `status=PASS`，Step4 validator 也没有把该 sparse signal 升级成阻断错误。

因此，当前 Alpha015 不能进入 candidate library / official library，也不应继续 Step6 promotion 判断；必须先修 formal evidence gate，再重跑 Alpha015。

## 核心证据

正式 factor values：

`runs/ALPHA015_SWEEP_TURNPEN_A040_20160101/factor_values__ALPHA015_SWEEP_TURNPEN_A040_20160101.parquet`

```text
rows: 8,034,990
date_count: 2,313
ticker_count: 5,004
factor_value_non_null: 92,716
factor_value_non_null_coverage: 1.15%
nonnull_date_count: 47
nonnull_start: 20160120
nonnull_end: 20160331
```

正式 factor signal：

`runs/ALPHA015_SWEEP_TURNPEN_A040_20160101/factor_signal__ALPHA015_SWEEP_TURNPEN_A040_20160101.parquet`

```text
rows: 8,034,990
factor_value_non_null: 92,716
nonnull_start: 20160120
nonnull_end: 20160331
```

Step4 self-quant payload：

`evaluations/ALPHA015_SWEEP_TURNPEN_A040_20160101/self_quant_analyzer/evaluation_payload.json`

```text
signal_rows: 8,034,990
signal_non_null: 92,716
merged_rows: 92,707
rank_ic_count: 47
status: success
```

Step4 diagnostics：

`objects/validation/factor_run_diagnostics__ALPHA015_SWEEP_TURNPEN_A040_20160101.json`

```text
run_status: partial
quality_checks.null_ratio.factor_value: 0.9884609688375467
quality_checks.window_complete: false
issues: []
```

Ultimate wrapper proof：

`objects/runtime_context/ultimate_run_report__ALPHA015_SWEEP_TURNPEN_A040_20160101.json`

```text
status: PASS
```

这说明系统已经观察到了 `run_status=partial` 和 `null_ratio=98.85%`，但没有把它们变成阻断。

## 更精确的问题描述

这次不只是“Step3B sample 被直接复用”。

当前 metadata 显示：

```text
step4_factor_io_profile.source: step4_recompute_fallback
step4_factor_io_profile.recomputed_factor: true
step3b_compute_cache_source.reusable: false
step3b_compute_cache_source.reason: universe_hash
```

也就是说，Step4 声称执行了 formal recompute；但 recompute 结果仍然只在 Step3B sample window 附近有非空值。

数据输入本身看起来是 full-window：

```text
input_io_profile.source: factorforge_data_api_full_query
clean_daily_bar: 20160101-20250711
daily_basic: 20160101-20250711
signal_daily_path rows: 8,034,990
```

所以更准确的框架缺口是：

1. Step4 formal factor parquet 允许“full row shell + sparse factor_value”存在；
2. Step4 diagnostics 记录了高 null ratio，但 validator 没有阻断；
3. self-quant 在 47 个非空交易日上给出成功评价；
4. Ultimate wrapper 把 partial Step4 仍包装为 PASS；
5. supplemental window evidence 与 formal Step4 evidence 互相矛盾时，系统没有强制 BLOCK。

## 应增加的硬性 gate

建议在 Step4 writer 和 Step4 validator 两层都加 guard。

### 1. Formal signal non-null coverage gate

对 formal factor values / factor signal 计算：

```text
factor_value_non_null_coverage = non_null(factor_value) / row_count
nonnull_date_count = nunique(trade_date where factor_value is not null)
nonnull_start / nonnull_end
```

若是 daily full-window formal evidence，应满足类似：

```text
factor_value_non_null_coverage >= 0.90
nonnull_date_count ~= active_date_count after formula lookback
nonnull_end close to effective_target_end
```

滚动窗口导致的前若干天空值是正常的，但不应出现从 `20160401` 到 `20250711` 全部为空。

### 2. Partial run cannot be promotion-gate evidence

如果：

```text
run_status: partial
quality_checks.window_complete: false
```

则：

```text
promotion_gate_evidence=false
can_enter_step5=false 或 Step5/Step6 必须标记 research_quality_blocked
ultimate wrapper status 不应是 PASS，至少应是 BLOCK / PARTIAL_NON_PROMOTABLE
```

### 3. Self-quant coverage sanity gate

如果：

```text
rank_ic_count << target active_date_count
merged_rows << signal_rows
signal_non_null / signal_rows < threshold
```

self-quant payload 不应输出 `status=success` 支撑正式评价，应输出明确 blocker，例如：

```text
BLOCK_STEP4_FORMAL_SIGNAL_NON_NULL_COVERAGE_LOW
BLOCK_STEP4_SELF_QUANT_EFFECTIVE_WINDOW_TOO_SHORT
```

### 4. Evidence-surface consistency gate

如果 `objects/window_evidence/...json` 与 formal Step4 evidence 不一致，例如：

```text
window_evidence.factor_coverage: 99.22%
formal_step4.factor_non_null_coverage: 1.15%
```

系统应保守选择 BLOCK，而不是让更好看的 supplemental evidence 覆盖 formal evidence。

### 5. Required output metadata

建议 Step4 metadata 增加：

```json
{
  "formal_signal_coverage": {
    "row_count": 8034990,
    "factor_value_non_null": 92716,
    "factor_value_non_null_coverage": 0.011539052,
    "nonnull_date_count": 47,
    "nonnull_start": "20160120",
    "nonnull_end": "20160331",
    "coverage_gate_verdict": "BLOCK"
  }
}
```

这样 Step5/Step6/Council 不需要重新扫描 parquet，也能直接知道 formal evidence 是否可用于 promotion gate。

## 修复后验收标准

修复后请重跑 Alpha015 parent formal Step3B/Step4，至少证明：

```text
repo_sha: <current>
report_id: ALPHA015_SWEEP_TURNPEN_A040_20160101
step4 source: factorforge_data_api_full_query
formal_factor_values_owner: Step4
run_status: success
window_complete: true
factor_value_non_null_coverage >= 0.90
nonnull_date_count close to active_date_count after max formula lookback
rank_ic_count close to active_date_count after forward-return availability
self_quant status: success
validator verdict: PASS
ultimate wrapper status: PASS
```

如果暂时只能产生 sample proof，则必须明确：

```text
promotion_gate_evidence=false
evidence_role=diagnostic_or_executability_only
official_factor_library_allowed=false
candidate_library_allowed=false
```

## 研究侧当前动作

研究侧已将 Alpha015 标记为：

```text
economic_logic: still_promising
formal_artifact_status: blocked
candidate_library_status: blocked_pending_formal_signal_coverage_repair
official_factor_library_allowed: false
next_valid_action: framework_repair_then_rerun_formal_step4
```

修复前，我不会继续用 Alpha015 当前 formal artifacts 做 stochastic validation、Council promotion、candidate library writeback 或 child revision。
