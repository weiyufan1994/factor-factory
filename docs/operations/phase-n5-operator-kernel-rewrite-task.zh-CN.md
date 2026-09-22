# Phase N.5 Operator Kernel Rewrite 任务说明书

## 背景

Phase N.2-N.4 已经证明：

- Step3A/Step3B/Step4 的 Parquet IO 合同有效，Alpha017 的 `read_inputs` 和 Step4 `load_daily_snapshot` 已明显下降。
- `sample_csv` policy 有效，Step3B CSV 写出已经不再是主要瓶颈。
- Formula-IR memoization 对 Alpha017 帮助有限。
- `numpy_sliding_window_experimental` 在 synthetic 上快，但 Alpha017 全量 benchmark 显著变慢，不能推广。
- Polars experimental backend 在 Alpha017 上因为 `unsupported_operator:mean` fallback 到 pandas，导致 `compute_factor` 变慢，也不能推广。
- 当前主要瓶颈仍在 Step3B Formula-IR operator execution，尤其是 `ts_rank` 和部分 rolling operators。

因此 Phase N.5 目标不是继续调 wrapper 或 Step4，而是重构 Formula-IR operator kernel 层：在不改变研究语义、不改变默认路径的前提下，为 rolling/ts operators 建立可审计、可 benchmark、可 fallback 的 optimized kernel 框架。

## 总目标

建立 `factor_factory.formula` 下的 operator kernel framework，让 Formula-IR evaluator 不再把每个算子硬写成 `groupby().rolling()`，而是通过可插拔 kernel registry 调用。

第一阶段只允许新增 experimental optimized kernels，默认路径仍必须是 pandas reference / pandas optimized；任何新 kernel 进入正式运行必须显式 opt-in，并通过 pandas reference parity、runtime guard、Alpha017 benchmark 之后才可考虑推广。

## 严格边界

本任务只允许修改 Step3B Formula-IR operator execution 相关代码和 smoke/profile 脚本。

允许修改：

- `factor_factory/formula/`
- `skills/factor-forge-step3/scripts/run_step3b.py`
- `scripts/run_factorforge_performance_smoke.py`
- `scripts/run_factorforge_performance_profile.py`
- `scripts/run_ts_rank_candidate_benchmark.py` 如需要
- `skills/factor-forge-step3/SKILL.md`

除非确有必要，不要修改 Step3A/Step4。严禁修改：

- Step5 / Step6 / Revision Council / promotion gate
- clean data 处理逻辑
- search worker
- factor research conclusion
- Step4 label timing contract
- official library promotion

不得把任何 optimized kernel 设为默认。

## 设计要求

### 1. 新增 kernel abstraction

建议新增目录：

```text
factor_factory/formula/kernels/
  __init__.py
  base.py
  pandas_reference.py
  pandas_optimized.py
  numpy_rolling.py
  optional_numba.py
```

如果实现者认为目录过重，也可以先放在单文件 `factor_factory/formula/kernels.py`，但必须保持接口清晰。

Kernel interface 至少覆盖：

```text
rank(series, frame)
ts_rank(series, window, frame)
ts_mean(series, window, frame)
ts_sum(series, window, frame)
ts_std(series, window, frame)
ts_min(series, window, frame)
ts_max(series, window, frame)
ts_delta(series, window, frame)
ts_delay(series, window, frame)
rolling_corr(left, right, window, frame)
rolling_cov(left, right, window, frame)
```

第一阶段不要求全部 optimized，但 reference path 必须完整。

### 2. 保留 pandas reference oracle

当前 pandas reference 语义是正式 correctness oracle，不得删除或弱化。

必须保持以下语义：

- `rank`: 按 `trade_date` 做 cross-sectional `rank(method="average", pct=True)`。
- `ts_rank`: 按 `ts_code` 分组；窗口不足输出 NaN；窗口内任一 NaN 输出 NaN；ties 使用 average rank；输出 percentile rank。
- rolling operators: 按 `ts_code` 分组，不允许跨股票窗口。
- unsorted input: evaluator 必须保证 reference / optimized 输出在 key order 上一致。

### 3. Kernel selection 必须显式

新增 kernel engine config，例如：

```text
FACTORFORGE_FORMULA_KERNEL_ENGINE=pandas_reference|pandas_optimized|numpy_rolling_experimental|numba_rolling_experimental
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1
run_step3b.py --formula-kernel-engine <engine>
```

要求：

- 默认仍是当前 pandas path。
- 任何 experimental engine 没有 enable gate 必须 BLOCK。
- invalid engine 必须 BLOCK，输出明确 token。
- legacy env 不得隐式启用 experimental kernel。

建议 BLOCK tokens：

```text
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_NOT_ENABLED
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_INVALID
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_DEPENDENCY_MISSING
```

### 4. 优先实现的 optimized candidates

优先级如下：

#### P0: rolling mean/sum/min/max/std

这些比 `ts_rank` 更容易安全优化，也能解决 Polars Alpha017 fallback 中 `mean` unsupported 的根因。

候选实现：

- NumPy cumulative sum for `mean/sum`
- deque / vectorized approach for `min/max`，如实现复杂可先保留 pandas
- std 可以先用 cumulative sum + cumulative square sum，但必须严格 parity；如果 `ddof` 不一致，直接不启用

#### P1: ts_rank per-ticker loop candidate

不要继续用全局 `sliding_window_view` 作为主方向。

新的 candidate 应该：

- 按 `ts_code` 分段处理连续数组。
- 避免构造巨大 window matrix。
- 优先考虑 `numba` optional kernel；如果环境无 numba，必须 dependency BLOCK 或 skip，不得默认依赖。
- 如果不用 numba，也要保证内存复杂度可控。

#### P2: rolling corr/cov

可先只做 profiling 和 candidate harness，不要求 formal Step3B opt-in。

## Profile 合同

Step3B metadata 必须新增或扩展：

```text
performance_profile.formula_engine_profile.kernel_profile
```

至少包含：

```json
{
  "version": "factorforge_formula_kernel_profile_v1",
  "selected_engine": "pandas_optimized",
  "experimental_enabled": false,
  "selection_source": "default|env|cli",
  "operator_call_count": 0,
  "by_operator": {},
  "fallback_reasons": [],
  "parity_checked": false,
  "parity_sample_rows": 0,
  "parity_max_abs_diff": null,
  "parity_nan_mask_equal": null,
  "parity_key_order_equal": null,
  "runtime_guard_seconds": null,
  "runtime_guard_passed": true,
  "safe_to_make_default": false
}
```

`safe_to_make_default` 必须保持 `false`，除非未来单独 Phase 经 reviewer 和用户批准。

## Parity 合同

每个 optimized candidate 必须与 pandas reference 比较：

- row count equal
- key order equal
- NaN mask equal
- max absolute diff <= `1e-12`，或针对浮点 std/corr/cov 给出明确 tolerance
- rank correlation >= `0.999999`，如果全等或全 NaN 导致不可计算，需要记录原因

Parity 失败必须 BLOCK，不允许 silent fallback 后宣称 optimized 成功。

## Runtime guard

Experimental formal run 必须支持 runtime guard，例如：

```text
FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS=90
```

如果 candidate 超时，必须 BLOCK：

```text
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD
```

不要像 N.3B 一样让全量 benchmark 在已经明显变慢时继续被误解为候选成功。

## Smoke 要求

新增或扩展 `scripts/run_factorforge_performance_smoke.py`，覆盖：

1. default path remains pandas
2. experimental kernel requires explicit enable
3. invalid kernel blocks
4. rolling mean/sum parity
5. rolling std parity or explicit unsupported skip
6. ts_rank candidate parity on ties/NaN/multiple tickers/unsorted input
7. parity failure blocks via `/tmp` fault injection
8. runtime guard blocks
9. metadata `kernel_profile` present
10. non-`/tmp` root blocks
11. canonical pollution false

如引入 optional dependency，例如 numba：

- dependency missing must SKIP or BLOCK clearly
- smoke 不得把 dependency missing 伪装成 actual optimized compute PASS

## Benchmark 要求

不要自动跑 Alpha017 full benchmark。实现完成并 smoke/reviewer accept 后，再由用户明确批准。

如果用户批准 Alpha017 benchmark，应使用正式 wrapper：

```bash
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1 \
FACTORFORGE_FORMULA_KERNEL_ENGINE=<candidate> \
FACTORFORGE_CSV_OUTPUT_POLICY=sample_csv \
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --start-step 3b \
  --end-step 4 \
  --council-mode off
```

之后运行：

```bash
python3 scripts/run_factorforge_performance_profile.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --write-report
```

必须报告：

- wrapper rc/status
- proof path
- profile path
- compute_factor before/after
- operator/kernel profile
- metric parity
- clean data unchanged
- no search worker
- no Step6/Council/promotion
- official record absent

## Acceptance Criteria

Coder 完成后必须提供：

- 修改文件列表
- `py_compile` PASS
- performance smoke `ACCEPT`
- Step12 regression `ACCEPT`
- Step6 intelligence acceptance `STEP6_INTELLIGENCE_ACCEPTED`
- Phase M loop smoke `ACCEPT`
- installed Step3 diff clean，如 Step3 skill 有改动
- 明确确认没有跑 Alpha017 full benchmark，除非用户批准
- 明确确认没有改 Step6/Council/promotion/clean data/search worker

## Reviewer 重点

Reviewer 应重点检查：

1. 默认路径是否仍为 pandas，且未被 env 泄漏改变。
2. pandas reference oracle 是否被保留。
3. experimental engine 是否必须显式 enable。
4. parity 失败是否硬 BLOCK，而不是 fallback 后 PASS。
5. runtime guard 是否真实阻断。
6. metadata 是否能区分：
   - actual optimized used
   - fallback used
   - dependency missing
   - unsupported operator
   - parity failed
   - runtime guard failed
7. smoke 是否覆盖真实 subprocess path，不只是 helper 函数。
8. 是否没有触碰 Step6/Council/promotion/clean data/search worker。

## 非目标

本阶段不做：

- 将 Polars 设为默认。
- 将任何 optimized kernel 设为默认。
- 重新解释 Alpha017 研究结论。
- 改 Step4 label alignment。
- 改 Step6 decision / Council behavior。
- 做 official promotion。
- 做 clean data 重建。

