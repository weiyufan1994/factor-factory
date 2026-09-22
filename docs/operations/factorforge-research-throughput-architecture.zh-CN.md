# Factor Forge Research Throughput Architecture

状态：探索架构

日期：2026-05-22

适用范围：Step3B / Step4 研究效率、IO 复用、排序治理、backend preflight、backend timing、operator rolling kernel 实验

不适用范围：正式 promotion、clean data 重建、search worker、生产默认强制切换、无 parity 的 operator 语义替换

## 1. 背景

Alpha029 的实际运行显示，研究效率瓶颈不只是单个 operator 慢，而是全量流水线成本叠加：

- Step3B 约 98 秒，Step4 约 179 秒。
- Step3B `compute_factor` 约 35 秒。
- Step3B `normalize_sort` 约 38 秒，已经超过计算本身。
- full CSV 写出约 16 秒，factor CSV 约 439MB。
- self_quant 约 44 秒。
- qlib backend 在缺少 provider 时仍启动，最终失败并浪费 backend 时间。

本轮已完成的生产级修复是：Step4 在 Step3B factor parquet 已存在时复用该 parquet，不再 import `factor_impl` 或调用 `compute_factor` 重算。该修复已进入 `main@5c07073`，并同步至 Mac / GitHub / openclaw-new / factor-research-worker。

本文处理的是后续探索架构：如何把 Alpha029 暴露的问题抽象为长期研究效率原则，尤其为未来分钟数据规模提前约束 IO、排序、CSV、backend、rolling kernel 的成本。

## 2. 总原则

Factor Forge 的研究效率优化必须遵守五条原则：

1. **可复用产物不重复计算**  
   report-scoped、identity 可信、hash 可信的 parquet / cache / intermediate table 应被复用。任何 fallback 重算都必须记录原因。

2. **正式证据以 parquet 为主，CSV 是 audit sample**  
   大规模正式因子值、daily input、merged evaluation table 不应以 full CSV 作为默认证据格式。CSV 用于人工抽样、schema audit、debug，不用于大表主路径。

3. **排序证明前移，Step3B 不反复证明全表有序**  
   如果 Step3A 或 clean/source layer 已经给出可信 sort contract，Step3B 应优先验证 contract、hash、抽样边界和 duplicate key，而不是每轮对 1000 万行以上数据做全量 sort/equality check。

4. **backend 先 preflight，后重 IO**  
   qlib/native provider、依赖、配置缺失时，应在 Step4 调度层或 adapter 入口早标记 `skipped_native` / `blocked_native`，避免读取大表后失败。

5. **operator kernel 优化必须晚于流水线治理**  
   `ts_rank`、`argmin`、`argmax`、`corr`、`cov`、rolling mean/sum/std 等可以优化，但只能作为 opt-in 实验轨道，保留 pandas reference parity 和 fallback。不能因为加速牺牲公式语义。

## 3. 瓶颈 Taxonomy

| 类别 | 当前表现 | 长期风险 | 优先级 |
| --- | --- | --- | --- |
| 全量物化 | Step3B 默认可能写 full CSV，Alpha029 CSV 约 439MB | 分钟数据会进入几十 GB 级别 | P0 |
| 排序 / 有序性证明 | `normalize_sort` 与 sortedness check 接近或超过计算耗时 | 分钟数据下 `N log N` 或全量 equality check 不可运营 | P0 |
| Step 间重复计算 | Step4 曾重复 Step3B `compute_factor`，现已修复 | 其他 backend/cache 仍可能重复派生 label/merge | P0/P1 |
| backend 重复 IO | self_quant / qlib 各自读取 factor 和 daily | backend 数量增加时线性放大 IO | P1 |
| qlib provider 后置失败 | 缺 provider 后仍进入 backend path | 大表读取后失败，浪费时间且污染定位 | P0 |
| backend timing 粗粒度 | Step4 wall time 难拆 read/merge/evaluate/write | 后续优化继续靠推断 | P0 |
| rolling operator 内核 | pandas groupby rolling / apply 类算子慢 | 在分钟数据和大窗口下成为第二阶段瓶颈 | P2 |

## 4. Phase A：低语义风险的流水线优化实验

Phase A 不直接改变正式生产默认，只在 `/tmp` fixture、performance smoke、profile wrapper 或显式 opt-in 环境下验证。

### A1. CSV Policy 探索默认

目标：

- performance/profile 路径优先使用 `sample_csv`。
- 大表正式证据固定为 parquet。
- `no_csv` 作为分钟数据或超大表实验选项。

建议 metadata：

```json
{
  "csv_output_profile": {
    "version": "factorforge_csv_output_profile_v1",
    "formal_evidence_format": "parquet",
    "csv_output_policy": "sample_csv | no_csv | full_csv",
    "sample_csv_rows": 1000,
    "sample_schema_parity": true,
    "full_csv_absent_validated": true
  }
}
```

验收 smoke：

- `sample_csv` 下 Step4 能读取 parquet 并完成 self_quant。
- `no_csv` 下 validator 不因缺 full CSV 失败。
- legacy missing policy 仍兼容 full CSV。
- canonical roots 不写入测试产物。

风险：

- 人工审计便利性下降。必须用 sample CSV、schema、row count、checksum、read script 弥补。

### A2. qlib Backend Preflight

目标：

- Step4 在启动 qlib native path 前检查 provider/import/config。
- 缺 provider 时写 payload 和 timing，但不启动 native adapter 重 IO。

建议 metadata：

```json
{
  "qlib_preflight": {
    "version": "factorforge_qlib_preflight_v1",
    "provider_uri_checked": true,
    "provider_present": false,
    "native_attempted": false,
    "status": "skipped_native_missing_provider",
    "preflight_seconds": 0.012
  }
}
```

验收 smoke：

- `/tmp` fixture 缺 qlib provider。
- qlib native 不启动。
- self_quant 正常执行。
- Step4 总 status 明确是 partial backend evidence，而不是伪装成 qlib success。

风险：

- 不能把 native skip 写成成功 backtest。payload 必须保留 backend status。

### A3. Step4 Backend Timing Profile

目标：

- Step4 记录每个 backend 的 preflight、load、merge、evaluate、write、subprocess wall time。
- 后续定位不再依赖 wrapper 总耗时推断。

建议 metadata：

```json
{
  "backend_timing_profile": {
    "version": "factorforge_step4_backend_timing_profile_v1",
    "backends": {
      "self_quant_analyzer": {
        "attempted": true,
        "status": "success",
        "wall_seconds": 44.1,
        "load_seconds": 10.2,
        "merge_seconds": 8.7,
        "evaluate_seconds": 20.4,
        "write_seconds": 4.8
      },
      "qlib_native": {
        "attempted": false,
        "status": "skipped_native_missing_provider",
        "preflight_seconds": 0.012
      }
    }
  }
}
```

验收 smoke：

- backend 成功、backend skipped、backend failed 三类状态都有 timing。
- payload 路径、return code、stderr tail 有记录。
- profile 不影响 Step4 既有 output contract。

## 5. Phase B：排序与跨 Backend 复用

Phase B 是中等风险探索，必须先在 `/tmp` fixture 上证明 parity。

### B1. Sort Contract

问题：

Step3B 当前对大表做全量 sort / sortedness check。对 daily 1164 万行已经明显；分钟数据会把该成本放大到不可运营。

目标：

- Step3A 或 source layer 产出 `sort_contract`。
- Step3B 优先验证 contract，而不是每轮做全量排序证明。
- 只有 contract 缺失、不可信、hash 不匹配、抽样失败时才 fallback 全量 sort。

建议 contract：

```json
{
  "sort_contract": {
    "version": "factorforge_sort_contract_v1",
    "sorted_by": ["ts_code", "trade_date"],
    "partitioned_by": ["ts_code"],
    "row_count": 11640000,
    "key_dtype": {
      "ts_code": "string",
      "trade_date": "int64"
    },
    "source": "step3a_local_input",
    "data_hash": "<hash>",
    "sample_sortedness_check": true,
    "duplicate_key_check": true,
    "full_sort_skipped_reason": "trusted_step3a_sort_contract"
  }
}
```

必需 guard：

- row count 一致。
- key dtype 一致。
- duplicate `(ts_code, trade_date)` 检查。
- 每个 partition 的 min/max 或 boundary sample 检查。
- 小样本 full-sort parity replay。

风险：

- 错误 contract 会导致 rolling window、rank、delay、delta 语义错误。
- 因此它不能先作为生产默认，只能从 opt-in profile 实验开始。

### B2. Shared Evaluation Context

问题：

Step4 主流程已经能复用 Step3B factor parquet，但 backend 子进程仍可能分别读取 factor/daily、分别 merge、分别计算 forward return 或 quantile assignment。

目标：

Step4 在 report-scoped run dir 中生成共享窄表：

- `factor_signal__<report_id>.parquet`
- `daily_forward_returns__<report_id>.parquet`
- `merged_signal_return__<report_id>.parquet`
- `quantile_assignment__<report_id>.parquet`

backend 只读取这些 shared context，不再重复构造相同中间表。

建议 identity：

```json
{
  "shared_evaluation_context": {
    "version": "factorforge_shared_evaluation_context_v1",
    "report_id": "<report_id>",
    "factor_id": "<factor_id>",
    "implementation_mode": "operator | direct_code | hybrid",
    "spec_hash": "<hash>",
    "code_hash": "<hash>",
    "factor_values_hash": "<hash>",
    "daily_input_hash": "<hash>",
    "label_policy": {
      "horizon": "T+1",
      "return_type": "simple",
      "price_field": "close"
    },
    "cache_hit": true,
    "invalidated_reason": null
  }
}
```

验收 smoke：

- shared context 输出与 backend 自建输出 parity。
- 任一 identity 字段不匹配时拒绝复用。
- backend payload 标记 `shared_context_source`。

风险：

- 最大风险是错用旧 factor、旧 label horizon、旧 branch/run。identity 必须严格。

## 6. Phase C：Rolling / Groupby Rolling Kernel 实验

DeepSeek 和量化同学的建议方向是合理的：rolling 慢的根源通常是 Python 层循环、`groupby().rolling().apply()`、`groupby.apply(lambda ...)` 以及重复构造窗口。优化方向应是把计算下沉到 pandas 内置 C path、NumPy、Numba 或专用 kernel。

但 Factor Forge 不能采用“零代码替换就默认启用”的方式。任何 kernel 替换都必须证明 Formula-IR 语义不变。

### C0. 先消除低级慢路径

规则：

- 能用 pandas 内置 rolling 聚合就不用 `apply`。
- 必须 `apply` 时优先 `raw=True`。
- `groupby.apply(lambda x: x.rolling(...))` 应改为直接 `groupby(...)[col].rolling(...).agg()` 或 Formula-IR kernel registry。

适用算子：

- `mean`
- `sum`
- `min`
- `max`
- `std`
- `delta`
- `delay`

风险较低，但仍需 parity。

### C1. Online / Cumulative Formula

量化同学提到的 rolling mean 优化，本质是维护窗口和与滑出值：

```text
rolling_sum[t] = rolling_sum[t-1] + x[t] - x[t-window]
rolling_mean[t] = rolling_sum[t] / window
```

这类方法适合：

- rolling sum
- rolling mean
- rolling count
- rolling variance/std 的 Welford 或 prefix-sum 变体

它不适合直接泛化到：

- rolling rank / ts_rank
- argmin / argmax with tie semantics
- corr / cov with NaN/tie/window edge cases

建议：

- 先实现为 `numpy_rolling_experimental` 的候选 kernel。
- 每个 operator 单独注册，不做全局 monkey patch。

### C2. NumPy Sliding Window

`numpy.lib.stride_tricks.sliding_window_view` 可把窗口构造成视图，然后用 NumPy 聚合。

适用：

- 中等窗口、连续数组、内存可控的 rolling 聚合。

风险：

- 视图本身零拷贝，但下游聚合可能 materialize 大矩阵。
- 对分钟数据、长窗口、多列、多股票，内存可能爆。
- 必须按 `ts_code` 分组，不能跨股票窗口。

结论：

- 可作为 benchmark candidate。
- 不应作为默认 large-data kernel。

### C3. Numba Kernel

Numba 适合自定义循环和复杂 rolling logic：

- `ts_rank`
- `argmin`
- `argmax`
- rolling range
- 部分 rolling corr/cov

约束：

- 只允许 opt-in：`FACTORFORGE_FORMULA_KERNEL_ENGINE=numba_rolling_experimental`。
- 必须记录 numba 是否可用、compile time、runtime、fallback reason。
- CI/smoke 不应依赖远端机器一定安装 numba，缺失时应明确 skip/fallback。

### C4. 专用库 / Monkey Patch

DeepSeek 提到的 `unlockedpd`、`window-ops`、`numbagg`、`cudf.pandas` 只能作为 benchmark 对照，不应直接进入生产默认。

原因：

- `cudf.pandas` 依赖 GPU 和 RAPIDS 环境，Mac/EC2/研究机不可保证一致。
- monkey patch pandas 会扩大 blast radius，不利于 provenance 和 debug。
- 专用库可能改变 NaN、tie、min_periods、dtype、index alignment 语义。

允许方式：

- 独立 benchmark script。
- 明确 engine name。
- 输出 parity report。
- 不写正式 factor artifacts。

## 7. Kernel Parity Contract

任何 optimized rolling kernel 都必须相对 pandas reference 证明：

```json
{
  "kernel_parity_profile": {
    "version": "factorforge_kernel_parity_profile_v1",
    "operator": "ts_rank",
    "reference_engine": "pandas_reference",
    "candidate_engine": "numba_rolling_experimental",
    "row_count": 11640000,
    "sample_rows": 100000,
    "key_order_equal": true,
    "nan_mask_equal": true,
    "max_abs_diff": 0.0,
    "rank_corr": 1.0,
    "tie_policy_equal": true,
    "window_boundary_equal": true,
    "runtime_guard_passed": true,
    "safe_to_make_default": false
  }
}
```

默认原则：

- `safe_to_make_default` 初始必须为 `false`。
- 只有长期多报告、多公式、多机器 benchmark 通过后，才允许讨论默认切换。

## 8. 分钟数据前置设计

分钟数据会把成本从“慢”变成“结构性不可运营”：

- 行数按 `daily_rows * bars_per_day` 放大。
- full CSV 可能从数百 MB 进入几十 GB。
- sort / sortedness check 从可忍受变成 blocker。
- backend 重复读取和 merge 会按 backend 数量线性放大。
- rolling / groupby rolling 会成为第二阶段主要 CPU 热点。

分钟数据进入前必须有：

1. parquet-only formal evidence。
2. partition/order contract。
3. shared evaluation context。
4. backend preflight。
5. backend timing profile。
6. minute label policy：bar close、next bar/next day、停牌、集合竞价、撮合边界。
7. row/bytes budget blocker。

建议 blocker：

```json
{
  "minute_data_cost_budget": {
    "version": "factorforge_minute_cost_budget_v1",
    "estimated_rows": 2500000000,
    "estimated_factor_parquet_gb": 40.0,
    "estimated_full_csv_gb": 180.0,
    "backend_count": 3,
    "full_csv_allowed": false,
    "full_sort_allowed": false,
    "requires_shared_evaluation_context": true,
    "requires_preflight": true
  }
}
```

## 9. 推荐实验顺序

### Experiment 1：只读性能归因增强

输入：已有 Alpha029 / Alpha017 artifacts。

输出：

- Step3B phase timing。
- Step4 backend timing gap。
- CSV bytes / parquet bytes。
- sort / compute / write / backend ratio。

禁止：

- 不跑 wrapper。
- 不读 clean data。

### Experiment 2：qlib Preflight Smoke

输入：`/tmp` fixture，缺 qlib provider。

验证：

- native 不启动。
- payload 完整。
- status 明确。
- self_quant 不受影响。

### Experiment 3：CSV Policy Smoke

输入：`/tmp` fixture。

验证：

- `sample_csv` 和 `no_csv` 不影响 Step4 evidence。
- validator 接受 parquet formal evidence。
- sample CSV schema parity。

### Experiment 4：Sort Contract Parity

输入：小样本和中样本 fixture。

验证：

- trusted sort contract 跳过 full sort。
- 输出与 full sort 路径 parity。
- 乱序、重复 key、dtype mismatch 会触发 fallback 或 BLOCK。

### Experiment 5：Shared Evaluation Context 原型

输入：`/tmp` fixture。

验证：

- self_quant / qlib stub 复用 shared merged table。
- payload parity。
- identity mismatch 拒绝复用。

### Experiment 6：Rolling Kernel Benchmark

输入：合成 Formula-IR fixtures 和已有 performance profile。

候选：

- pandas 内置聚合重写。
- online rolling sum/mean。
- NumPy sliding window。
- Numba rolling kernel。
- 专用库 benchmark 对照。

验证：

- pandas reference parity。
- runtime speedup。
- memory peak。
- fallback reason。

## 10. 不做事项

本探索架构明确不做：

- 不自动把 production default 改成 `no_csv`。
- 不把 `cudf.pandas` 或 `unlockedpd` monkey patch 到正式入口。
- 不绕过 pandas reference parity。
- 不在缺 qlib provider 时伪造 qlib 成功。
- 不跨 factor/report/branch/run 复用 cache。
- 不处理 clean data。
- 不运行 search worker。
- 不写 official promotion。

## 11. 建议近期任务拆分

建议按以下顺序立项：

1. `research-throughput-profiler-design`
   - 只读性能归因。
   - 目标是让每轮慢点可解释。

2. `step4-qlib-preflight-and-backend-timing`
   - 低语义风险，直接减少无效 backend 时间。

3. `csv-policy-parquet-formal-evidence-smoke`
   - 为 sample/no CSV 默认实验扫清 validator 风险。

4. `step3b-sort-contract-experiment`
   - 高收益但高语义风险，必须先 parity。

5. `step4-shared-evaluation-context-prototype`
   - 为分钟数据前的 backend 复用打底。

6. `formula-rolling-kernel-benchmark`
   - 第二阶段 CPU kernel 优化，严格 opt-in。

## 12. 架构结论

研究效率提升的主线不是先重写 operator，而是先治理流水线：

1. 少写大 CSV。
2. 少做全量排序证明。
3. 少重复读取和 merge。
4. 少启动注定失败的 backend。
5. 把 backend timing 拆清楚。
6. 最后再优化 rolling kernel。

DeepSeek 的 rolling 优化建议可以吸收，但必须落在 Formula-IR kernel registry 和 parity profile 之内。零代码替换、GPU monkey patch、全局 pandas patch 都只能作为 benchmark 对照，不能作为 Factor Forge 的正式语义路径。

