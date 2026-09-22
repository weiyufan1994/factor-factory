# Factor Forge Step3 数据就绪与 worker 执行问题反馈

Date: 2026-05-30

Audience: Factor Forge Architect / Step3 coder / reviewer

## 1. 结论

本反馈基于 `kaiyuan_20200516_amplitude_factor_hidden_structure` 最新 Step3 路径的 artifact、S3、SSM、研究机只读检查结果。结论如下：

1. Humphrey 发现 `data_prep_master.feasibility=blocked` 和 `SHARED_CLEAN_DAILY_LAYER_MISSING` 是真实的 artifact 状态。
2. 但将问题归因为“研究机数据或环境不足”不准确。S3 canonical clean daily 存在，研究机 run root 下也已经出现 `daily_input` 和 `factor_values`。
3. 当前真实问题是 Step3A 数据解析边界、Step3 readiness gate、Step3B direct_code 生成与验证契约没有闭环。
4. Humphrey 没有真正解决问题。`ultimate_run_report` 仍是 `FAIL`，失败点是 `validate_step3b`。
5. 当前不应把该 run 视为 Step3B/Step4/Step5 成功，也不应进入 Step6 研究结论或 library writeback。

## 2. 本次审计对象

```text
report_id = kaiyuan_20200516_amplitude_factor_hidden_structure
run_id    = 20260529T154706762813Z_kaiyuan_20200516_amplitude_factor_hidden_structure_step1_6d29236ea9d1
repo_sha  = 7909c7c0c543a6457d7eb7879025eb98e6db132d
worker    = i-02cc0b6e93856fbb4
visible Humphrey SSM command = ebbb4e68-2dfc-4d89-84a7-ebf5d1cf424c
```

审计时临时启动研究机做只读检查。检查完成后已停止研究机。

## 3. 事实证据

### 3.1 Humphrey 报告的 BLOCK 项确实存在

`data_prep_master__kaiyuan_20200516_amplitude_factor_hidden_structure.json` 中：

```json
{
  "feasibility": "blocked",
  "blocked_items": [
    {
      "code": "SHARED_CLEAN_DAILY_LAYER_MISSING",
      "detail": "Shared clean daily layer is missing under .../data/clean; run scripts/build_clean_daily_layer.py before Step 3A."
    }
  ],
  "daily_filter_policy": null
}
```

这说明 Step3A artifact 层面确实没有证明有效交易日过滤策略，也没有证明它从 shared clean daily layer 读取了正式输入。

### 3.2 S3 canonical clean daily 实际存在

S3 上存在：

```text
s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet
s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.meta.json
```

因此 `SHARED_CLEAN_DAILY_LAYER_MISSING` 不能解释为“系统没有日线数据”。它只能说明当前 Step3A runtime 没有把 canonical clean daily 解析到 run root 期望的位置。

### 3.3 研究机 run root 下也存在 daily input 和 factor values

研究机只读检查显示：

```text
.../runs/kaiyuan_20200516_amplitude_factor_hidden_structure/step3a_local_inputs/daily_input__kaiyuan_20200516_amplitude_factor_hidden_structure.parquet
.../runs/kaiyuan_20200516_amplitude_factor_hidden_structure/factor_values__kaiyuan_20200516_amplitude_factor_hidden_structure.parquet
```

`daily_input` schema 包含：

```text
ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount,
daily_basic_close, turnover_rate, turnover_rate_f, volume_ratio, pe, pe_ttm, pb, ...
```

这进一步说明“研究机没有数据”不是准确诊断。

### 3.4 visible SSM command 并非 RUNNING

Humphrey 汇报：

```text
ssm_command_id = ebbb4e68-2dfc-4d89-84a7-ebf5d1cf424c
status = RUNNING
```

实际 AWS SSM 结果：

```text
Status       = Failed
ResponseCode = 1
stdout       = [FAIL] run_step3b rc=1
```

该 command 在不到 1 秒内失败，不是等待 10 到 20 分钟的正常 worker 任务。

### 3.5 后续 artifact 显示 Step3B 仍失败

`ultimate_run_report__kaiyuan_20200516_amplitude_factor_hidden_structure.json`：

```json
{
  "status": "FAIL",
  "start_step": "3b",
  "end_step": "5",
  "failure": {
    "command": "validate_step3b",
    "returncode": 1
  }
}
```

失败栈：

```text
TypeError: compute_factor() got an unexpected keyword argument 'daily_df'
...
polars.exceptions.ComputeError: UDF failed: sub operation not supported for dtypes `str` and `str`
```

这说明 Step3B direct_code 代码契约和 validator smoke 调用契约不一致，并且生成实现对输入类型处理不可靠。

## 4. 根因归纳

### 4.1 Step3A 的 clean daily resolution 仍是本地路径导向

`run_step3.py` 当前核心逻辑是：

```text
if not clean_daily_layer_ready(CLEAN_DAILY_LAYER):
    snapshot_source = missing_clean_daily_layer
```

`CLEAN_DAILY_LAYER` 在 formal run 中被设置为：

```text
<artifact_root>/data/clean/daily_clean.parquet
<artifact_root>/data/clean/daily_clean.meta.json
```

这绕开了 S3 datamart / data catalog 的 canonical clean daily。只要 run root 没有本地 `data/clean`，Step3A 就报 blocked，即使 S3 有数据。

### 4.2 Data API package-first 架构没有成为 Step3A 硬边界

目标架构应是 Step3A 消费 `factor_factory.data_api`，解析 `clean_daily_bar` 数据集，并把 resolution 写入 `data_prep_master`、`qlib_adapter_config`、`handoff_to_step4`。当前实际代码仍在本地路径和 shared clean layer helper 之间切换。

### 4.3 `blocked` 和 `step3b_ready=true` 可以共存

`validate_step3.py` 允许：

```text
prep.feasibility = blocked
handoff.step3a_ready = false
handoff.step3b_ready = true
```

这制造了控制面矛盾：Step3A 明明没有证明数据就绪，Step3B/worker 却仍能被派发。

### 4.4 Step3B 代码契约没有验证真实 entrypoint 形态

生成代码中同时出现：

```python
def compute(daily_df, minute_df=None, ...)
def compute_factor(daily_df=None, minute_df=None, ...)
```

但 `validate_step3b` 先后尝试不同调用方式，最终触发：

```text
compute_factor() got an unexpected keyword argument 'daily_df'
```

这说明 validator 读取的 generated code 或 Step2 code contract 与 Step3B 生成代码不一致。Step3B 不能只检查“文本中有 compute_factor”，还必须 import 后检查签名、调用方式、输入 schema 与 smoke fixture 的一致性。

### 4.5 direct_code 对有效交易日过滤仍依赖输入侧假设

生成代码里：

```python
effective = np.ones(len(w_amp), dtype=bool)
```

这意味着 direct_code 本身不剔除停牌或一字涨跌停。它可以被接受的唯一前提是 Step3A artifact 明确证明输入已经是 clean daily，并写入 `daily_filter_policy`。当前这项证明缺失。

## 5. 对 Humphrey 汇报的评价

| Humphrey 说法 | 审计结论 |
|---|---|
| Step3A schema 层面 ACCEPT | 形式上成立，但业务上不应作为 Step3A 可继续信号 |
| `SHARED_CLEAN_DAILY_LAYER_MISSING` | artifact 中真实存在 |
| 日线或研究机数据不足 | 不准确。S3 有 canonical clean daily，研究机 run root 也有 daily input |
| worker command RUNNING | 不准确。visible command 实际 Failed |
| Step1/Step2/Step3A 均 ACCEPT，下一步启动 Step3B/Step4 | 控制面不严谨。Step3A `feasibility=blocked` 不应被等同于业务 ACCEPT |
| 问题已解决 | 不成立。`ultimate_run_report.status=FAIL` |

## 6. 必须修正的系统边界

1. Step3A 必须使用 Data API / catalog-first resolution，不能只查 run root 本地 clean layer。
2. `data_prep_master.feasibility=blocked` 时，handoff 不得出现 `step3b_ready=true`。
3. `daily_filter_policy` 是 direct_code 依赖 clean input 的必要证明字段，缺失时不得派发 worker。
4. Step3B 必须在生成代码后做 import/signature/schema/smoke 一致性验证。
5. Worker 汇报必须以 AWS SSM `Status/ResponseCode` 和 `ultimate_run_report.status` 为准，不能以“已派发”替代“运行中/成功”。
6. Step4/Step5/Step6 不得消费 `ultimate_run_report.status=FAIL` 的 evidence 作为研究成功样本。

## 7. 当前处置建议

本 run 应标记为 Step3 路径失败样本，不继续 Step6。

下一步不是重跑 Humphrey，而是先完成 Step3 数据就绪架构修正：

```text
Data API resolution -> Step3A readiness gate -> Step3B code contract smoke -> worker proof reporting
```

修完后再用同一篇报告开启 fresh run 或从允许的 Step3 边界重跑，具体取决于当时 registry/root SHA 是否仍匹配。
