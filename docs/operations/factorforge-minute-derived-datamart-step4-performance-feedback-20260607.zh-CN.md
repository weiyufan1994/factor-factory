# Factor Forge 分钟因子 Derived Datamart 与 Step4 性能反馈

日期：2026-06-07

对象：架构师 / coder / reviewer

相关 report：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_2026__aec8b09a34__LOOP01__MILLER_TAIL_PRICING_PERSISTENT_FLOW_STATE_V1
```

## 一句话结论

本轮 moneyflow / Miller child revision 证明了 Factor Forge 的 Step6 -> main-agent synthesis -> direct-code child materialization 链路已经能工作，但 full Step4 在分钟数据上暴露出长期生产瓶颈：不能让每个分钟因子、每个 child revision、每个 loop 都重新扫描并 groupby 全量 minute bars。

应先补一层通用的 `minute-derived datamart` / `intraday state cache` 基础设施，再继续大规模 2016-2026 分钟因子研究。

当前状态应记录为：

```text
mechanism_record: PASS
main_agent_synthesis: PASS
approval_bridge: PASS
child_materialization: PASS
Step3B sample proof: PASS
full Step4: BLOCK_PERFORMANCE_GENERIC_MINUTE_STREAMING
research_outcome: not_evaluable_until_step4_performance_fixed
```

## 本轮发生了什么

### 已完成

已写入研究记录：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_journal/research_journal__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.json
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_journal/miller_uncertainty_moneyflow_note__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.md
```

已写入主 agent Council synthesis：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_iteration_master/revision_council/ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221/main_agent_council_synthesis__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.json
```

approval bridge 通过：

```text
selected_law_id       = miller_tail_pricing_persistent_flow_state_v1
implementation_mode   = direct_code
parent_formula_hash   = 55e13114cd75c723f93210d6faf1a617acd4528eec7c8dfa48a6f98fead73f75
child_formula_hash    = 71c776c8f646987664105516d89e7380fa5dac6ccbd18ce7a01264dcd2f90ab1
validate_step6.rc     = 0
```

child materialization 通过：

```text
executable_revision_spec exists
child factor_spec_master exists
child data_prep_master exists
child handoff_to_step3 / handoff_to_step4 exists
generated_code_written = false
clean_data_touched = false
official_promotion_written = false
```

Step3B sample proof 通过：

```text
row_count   = 32
date_count  = 16
ticker_count = 2
```

### BLOCK 点

full Step4 对 child revision 运行约 30 分钟仍未产出：

```text
factor_evaluation__<child>.json
run_metadata__<child>.json
formal factor_values parquet
```

进程状态：

```text
run_step4.py alive
CPU roughly 70%
RSS roughly 8-12GB
machine memory still available
not OOM
not system-killed
```

最终由研究员主动取消 SSM command，避免留下不可观测长任务。

这不是因子经济机制的 reject，也不是 Council / child bridge 失败；这是 Step4 full minute computation 的性能 BLOCK。

## 为什么会慢

本轮 child revision 是 `direct_code`，为了避免旧 SP3 hard-coded fast path 重复 parent 公式，child source 故意避开旧 fast-path token。

结果 Step4 只能走 generic minute streaming：

1. 分批读取 minute partitions。
2. 每批调用 pandas `compute_factor(daily_df, minute_df)`。
3. 每批重新做：
   - 时间过滤；
   - bar return；
   - signed amount；
   - amount square；
   - groupby `ts_code, trade_date`；
   - cross-sectional z-score；
   - lagged daily_basic merge；
   - factor value 计算；
4. 在内存中累积 chunks。
5. 最后才写正式 factor values / evaluation。

这保证了 correctness，但不适合 2016-2026 生产规模。

## 不是所有分钟因子都能用同一个 daily aggregation

分钟因子应按可分解性分类。

### A. 可日度化的分钟因子

这类可以统一走 derived datamart：

```text
signed_flow
order_imbalance proxy
buy/sell pressure
HHI / concentration
intraday realized volatility
intraday noise
time-sliced pressure
morning / afternoon / tail pressure
close-auction proxy
path skewness / kurtosis
impact / elasticity
```

它们的共同点是：核心 observable 可以压缩成 `date x instrument` 或少量 `date x instrument x bucket` 状态。

### B. 半路径依赖因子

这类不能只保留一个 daily row，但可以保留更细状态：

```text
date x instrument x time_bucket
date x instrument x event_type
date x instrument x segment
```

例子：

```text
breakout timing
post-event 5/10/30 minute response
morning-to-afternoon state transition
tail pressure after high-volatility segment
```

### C. 强路径依赖 / sequence 因子

这类不能简单 daily preaggregation：

```text
full intraday sequence model
cross-instrument synchronization
lead-lag propagation inside day
minute-level regime switching with exact order dependence
```

它们仍然需要缓存，但缓存对象应是 event-level / bucket-level / sequence-feature parquet，而不是普通日频表。

## 推荐架构

### 1. 新增 minute-derived datamart 层

建议在 Data API / datamart 层维护：

```text
minute_derived_flow_state_v1
minute_derived_path_state_v1
minute_derived_time_bucket_state_v1
minute_derived_event_state_v1
```

以 moneyflow / SP3 为例，`minute_derived_flow_state_v1` 至少包含：

```text
ts_code
trade_date
cutoff_time
signed_pressure_sum
gross_pressure_sum
pressure_sq_sum
participation_concentration
minute_count
absolute_move_sum
intraday_ret_noise
morning_signed_pressure
afternoon_signed_pressure
tail_signed_pressure
tail_concentration
amount_total
source_minute_dataset_id
source_data_version
producer_version
artifact_hash
```

### 2. 按 date partition 写 parquet

推荐路径形态：

```text
s3://.../factorforge/datamart/minute_derived/flow_state/v1/trade_date=YYYYMMDD/*.parquet
```

本地 / EC2 cache：

```text
$FACTORFORGE_DATA_CACHE/minute_derived/flow_state/v1/trade_date=YYYYMMDD/*.parquet
```

核心目标：

```text
第一次 backfill 慢可以接受
同一数据版本下后续 factor/revision/loop 必须 warm-cache 快
```

### 3. Step3/Step4 声明式消费 derived states

factor_spec / data_prep_master 应允许声明：

```json
{
  "minute_derived_state_requirements": [
    {
      "dataset": "minute_derived_flow_state_v1",
      "cutoff_time": "14:50:00",
      "fields": [
        "signed_pressure_sum",
        "gross_pressure_sum",
        "participation_concentration",
        "intraday_ret_noise"
      ],
      "window_start": "2016-01-01",
      "window_end": "2025-07-11",
      "freshness_policy": "data_version_locked"
    }
  ]
}
```

Step4 逻辑：

1. 如果 derived state 完整命中，直接读 derived parquet。
2. 如果缺失，正式 production 不应默默扫全量 minute；应：
   - BLOCK；
   - 或提交 backfill job；
   - 或在明确 `allow_backfill=true` 时生成缺失分区。
3. derived state 读取和 factor evaluation 要进入 performance profile。

### 4. Step4 不应默认 generic minute streaming full window

generic minute streaming 可保留，但应定位为：

```text
debug / sample / small-window proof
```

正式 full research path 应有 guard：

```text
if full_window_days > threshold and minute_derived_state_missing:
    BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED
```

否则 2016-2026 会在每个 child / sibling / loop 上重复消耗几十分钟甚至更久。

## 2016-2026 规模问题

用户后续希望跑 2016-2026。

这意味着：

```text
10 years
约 2400+ trading days
5000+ instruments
minute bars 每日约 240 bars
```

直接 full streaming 的量级是：

```text
2400 * 5000 * 240 ≈ 2.88 billion instrument-minute rows
```

如果每个 child revision 都重新扫描，Factor Forge loop 会不可用。

必须改成：

```text
minute raw bars -> reusable derived states -> factor-specific daily expression -> Step4 evaluation
```

这也是空间换时间：S3/parquet 存储成本通常比反复 EC2 计算和研究等待更便宜，而且更可审。

## 研究 / 测试集切分新规则

用户已明确新规则：

```text
default research in-sample cutoff = 2025-07-11
2025-07 through latest available date = out-of-sample test set
```

建议写入 Step4 / Step5 / Step6 合同：

```json
{
  "research_window": {
    "in_sample_start": "2016-01-01",
    "in_sample_end": "2025-07-11",
    "oos_start": "2025-07-12",
    "oos_end": "latest_available"
  }
}
```

推荐 validator 规则：

```text
BLOCK_RESEARCH_WINDOW_SPLIT_MISSING
BLOCK_REVISION_USES_OOS_FOR_FITTING
BLOCK_PROMOTION_WITHOUT_OOS_EVIDENCE
```

Step6 / Council 只能基于 in-sample 结果提出 revision。OOS 用于最终验证，不用于反复调参。

## 需要 coder / 架构师做什么

### P0: minute-derived datamart contract

定义：

```text
dataset names
schema
partition layout
versioning
source data identity
cutoff_time identity
artifact hash
freshness semantics
warm-cache semantics
```

验收：

```text
Data API can query minute_derived_flow_state_v1 by date range and fields
missing partitions are explicit
negative cache works for non-trading dates
catalog exposes the derived dataset
```

### P0: Step4 full-window guard

正式路径应禁止在缺少 derived state 时默认扫全量 minute。

建议 blocker：

```text
BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED
BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN
BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE
BLOCK_MINUTE_DERIVED_STATE_IDENTITY_MISMATCH
```

### P1: derived-state backfill runner

新增 backfill 命令：

```bash
python3 scripts/build_minute_derived_datamart.py \
  --dataset minute_derived_flow_state_v1 \
  --start-date 2016-01-01 \
  --end-date 2025-07-11 \
  --cutoff-time 14:50:00 \
  --write-s3 \
  --write-local-cache
```

要求：

```text
date partitioned
resumable
idempotent
manifest written
profile written
failed dates recorded
```

### P1: Step4 performance profile split

Step4 profile 应拆开：

```text
load_derived_state
load_daily_controls
factor_expression_compute
factor_values_write
backtest_base_load
ic_calculation
quantile_nav
long_side
plots/tables
```

不要把 minute raw aggregation 混在 `compute_factor` 一个大桶里。

### P1: Step3B sample-only enforcement

Step3B 对 direct-code minute factor 应只做 sample proof：

```text
sample rows
sample dates
schema validation
information-set validation
source code import/compute validation
```

full factor values owner 应保持 Step4。

### P2: 新增 Miller / moneyflow fast path

当前 moneyflow Miller branch 可以作为第一类 derived-state consumer。

它需要的 derived fields：

```text
signed_pressure_sum
gross_pressure_sum
pressure_sq_sum
absolute_move_sum
intraday_ret_noise
minute_count
```

再合并 lagged daily_basic：

```text
total_mv
turnover_rate
turnover_rate_f
volume_ratio
pct_chg
```

## 需要 reviewer 看什么

reviewer 不应只看是否跑过一个 smoke，应重点检查：

1. 2016-2026 full window 下，Step4 是否不再走 generic minute streaming。
2. derived state identity 是否包含 source minute data version、cutoff time、schema version。
3. child revision 是否能复用 derived state，而不是每个 child 重算。
4. OOS split 是否被 Step5/Step6 尊重。
5. no clean data mutation / no official promotion / no search worker side effects 是否仍在 proof 中显式记录。

## 本轮本地窄修

本轮发现 approval bridge 的一个合同缺口：

```text
main_agent_council_synthesis 已经包含 selected law / expected metrics / falsification tests
但 approval bridge 没有把它映射成 validate_step6 要求的 revision_hypotheses
```

已做本地窄修：

```text
skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py
```

修复内容：

```text
approval bridge 自动生成 expression-level revision_hypotheses
补 primary_failure_signature
保留 no_portfolio_expression_repair / no_short_leg_adoption / no_decile_trading / no_shared_clean_data_mutation
```

验证：

```text
py_compile PASS
Mac installed skills synced
research worker synced
approval bridge PASS
validate_step6 rc=0
```

这属于长期合同修复，建议单独 commit / reviewer。

## 最终建议

短期：

1. 不要继续硬跑当前 generic minute streaming child。
2. 先补 `minute_derived_flow_state_v1` datamart 和 Step4 guard。
3. 用 Miller moneyflow child 做第一个 production proof。

中期：

1. 把主动资金流、HHI、大小单 proxy、dollar-bar proxy 都接入 derived datamart。
2. 支持 daily / time-bucket / event-level 三类分钟状态。
3. 将 2025-07-11 研究截止和 OOS 验证写入 Step5/6 promotion gate。

长期：

Factor Forge 的分钟因子研究应从：

```text
每个因子重复扫 minute bar
```

升级为：

```text
minute raw data -> reusable mathematical state library -> factor expression -> Step4 evaluation
```

这样才符合用户希望的 Dirac-style / physics-style 因子研究：先定义市场行为的可观测状态，再用数学机制推导表达式，而不是每轮在工程上重新读写原始分钟数据。
