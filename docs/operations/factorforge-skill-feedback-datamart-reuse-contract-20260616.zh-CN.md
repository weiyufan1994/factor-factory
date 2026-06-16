# Factor Forge Skill / Framework 数据状态复用合同反馈

Date: 2026-06-16

Audience: Factor Forge Architect / Ultimate / Step3 / Step4 / Step6 coder

Scope: 只反馈 skill/framework 合同问题，不评价 Moneyflow V20 因子有效性；不要求启动 clean data、search_worker、official promotion 或真实 production loop。

## 1. 结论

当前 Factor Forge 已经具备较强的 Dirac style research 能力，也已经开始通过 Data API 沉淀分钟 derived datamart。但研究流程仍有一个长期缺口：

> Council / Step6 每轮都可能生成新的 factor law，factor value 重算是合理的；但 Step3/Step4 不应每次都从 raw minute 重新构建可复用状态变量。

需要在 skill/framework 层新增 first-class contract：

1. 每个 factor law 必须声明自己依赖的 state variables。
2. Step3 在执行前必须先查 Data API catalog / state registry。
3. 已存在且 QA ACCEPT 的 datamart 必须复用。
4. 缺失 datamart 时，必须生成 `data_request_v1` 并 BLOCK，不能在 Step4 中临时扫多年 raw minute 做伪生产。
5. 研究完成后必须沉淀哪些 state 可复用、哪些 state 不应进入 Data API P0 schema。

这不是某个 moneyflow 版本的问题，而是 Factor Forge Ultimate 长期研究效率与可审计性的框架问题。

## 2. 用户关切

用户提出的核心问题是：

1. 每轮因子 revision 都不一样，是否最终还是要重算？
2. 哪些 feature / state 可以存下来复用？
3. Factor Forge 是否已经尽可能复用已有 datamart？
4. 新因子研究是否会反复把 raw minute 扫一遍？

正确边界应是：

- factor formula / law 经常变化，`factor_values` 重算是合理的；
- raw minute / moneyflow / daily_basic / universe / tradability 不应重复扫；
- intraday state、distribution moments、occupation measure、pseudo dollar bar 等“观测量 / 状态变量 / sufficient statistics”应沉淀为 reusable datamart；
- Step4 应在这些状态变量上组合、变换、筛选，而不是做 raw data engineering。

## 3. 当前已知可复用状态层

根据近期 Moneyflow / intraday research 记录，已有或正在沉淀的状态层包括：

- `daily_basic_backtest_base_is`
  - 用于 size、liquidity、turnover、universe、base return、tradability / controls。
- `intraday_flow_state_v2`
  - cutoff 前资金流状态，prior-date threshold，无未来分钟。
- `intraday_flow_distribution_moments_v1`
  - cutoff 粒度资金流分布形状，如 skewness、kurtosis、tail intensity。
- `intraday_pseudo_dollar_bar_v1`
  - 基于 1m bar 派生的 pseudo dollar bar，不是真 tick dollar bar。
- `intraday_value_occupation_state_v1`
  - 价格轴 occupation measure / POC / HVN / LVN / VA 类状态变量。
- `moneyflow_v20_slow_state_v1`
  - V20 event-triggered slow-state 方向，需按 Data API request 状态判断是否 ACCEPT。

这些数据不应被当作单个因子的私有临时文件，而应作为 Data API catalog 中可复用的数据产品。

## 4. 当前 skill/framework 缺口

### 4.1 Step3 缺少 state dependency resolution

现在 direct-code law 可以表达很复杂的研究逻辑，但 Step3 缺少一个结构化字段来声明：

```json
{
  "required_state_variables": [
    {
      "dataset_id": "intraday_flow_state_v2",
      "schema_version": "intraday_flow_state_v2_schema_v2.1",
      "window": "20160104-20250711",
      "cutoff_time": "14:50:00",
      "required_fields": ["flow_z", "large_flow_z", "ret_1450"],
      "no_future_intraday_minutes": true,
      "qa_required": true
    }
  ]
}
```

没有这个字段，研究员只能靠经验判断是否已有 datamart，容易出现重复建设或错误降级。

### 4.2 Step4 仍可能被迫承担数据工程

Step4 应该评估 factor value，而不是临时构建多年分钟 derived state。

建议 skill 明确：

- Step4 可以组合已 ACCEPT 的 state datamart；
- Step4 不允许在 production full-window 路径中直接扫多年 raw minute；
- 如果因子需要新的分钟状态变量，应先让 Step3 生成 `data_request_v1`；
- bounded smoke 可以跑小样本验证公式，但不得把 smoke 结果伪装为 full-window production proof。

### 4.3 Council revision 缺少 reuse-aware planning

Council / Step6 在提出 child revision 时，应先判断 revision 类型：

| Revision 类型 | 是否需要 raw minute | 应采取动作 |
|---|---:|---|
| 只改权重 / nonlinear transform / gate | 否 | 复用已有 state，快速重算 factor value |
| 新增已有 datamart 字段 | 否 | 复用 catalog 字段 |
| 新增未注册 state variable | 可能 | 先 bounded proof，再 data_request |
| 需要新 raw data | 是 | BLOCK 成 Data API request |
| 只改 portfolio policy / rebalance / holding | 否 | 不重算 factor value，只重跑 Step4 evaluation |

这张判断表应写入 Ultimate / Step6 skill，避免 Council 每次都把 revision 当成全新 raw-minute 研究。

## 5. 建议新增的合同字段

### 5.1 factor law dependency contract

每个 executable law / child spec 增加：

```json
{
  "state_dependency_contract": {
    "required_datasets": [],
    "required_fields": [],
    "allowed_missing_behavior": "block",
    "raw_minute_full_window_allowed": false,
    "bounded_smoke_allowed": true,
    "data_request_on_missing": true
  }
}
```

### 5.2 Step3 resolution report

Step3 输出：

```json
{
  "state_resolution": {
    "reuse_hits": [
      {
        "dataset_id": "intraday_flow_state_v2",
        "catalog_path": "...",
        "qa_path": "...",
        "coverage": "20160104-20250711",
        "verdict": "ACCEPT"
      }
    ],
    "missing_state_variables": [],
    "data_request_ids": [],
    "blocked": false
  }
}
```

### 5.3 Step4 provenance

Step4 metadata / performance profile 输出：

```json
{
  "state_datamart_reuse": {
    "reuse_hit": true,
    "datasets": ["intraday_flow_state_v2", "daily_basic_backtest_base_is"],
    "raw_minute_full_window_scan": false,
    "load_seconds_by_dataset": {}
  }
}
```

### 5.4 Step6 / Council synthesis

Council synthesis 输出：

```json
{
  "revision_data_plan": {
    "reuse_existing_state": true,
    "new_state_required": false,
    "data_request_required": false,
    "portfolio_only_revision": false,
    "factor_value_recompute_required": true
  }
}
```

## 6. 建议新增 BLOCK token

- `BLOCK_FACTORFORGE_STATE_DATAMART_MISSING`
- `BLOCK_FACTORFORGE_STATE_DATAMART_QA_NOT_ACCEPTED`
- `BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN`
- `BLOCK_FACTORFORGE_STATE_DEPENDENCY_UNDECLARED`
- `BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED`
- `BLOCK_FACTORFORGE_STATE_SCHEMA_VERSION_MISMATCH`
- `BLOCK_FACTORFORGE_STATE_COVERAGE_INSUFFICIENT`
- `BLOCK_FACTORFORGE_STATE_LOOKAHEAD_CONTRACT_MISSING`

这些 blocker 的目的不是增加流程成本，而是防止研究员为了继续跑而做 proxy/full-window 伪研究。

## 7. Skill 文档建议修改点

建议更新以下 skill：

- `factor-forge-ultimate`
  - 增加 “state dependency resolution before execution”。
  - 增加 “raw minute full-window scan forbidden unless explicitly approved”。
  - 增加 “data_request_v1 status gating”。
- `factor-forge-step3`
  - 增加 required state variables 解析与 Data API catalog lookup。
  - 缺 datamart 时生成 `data_request_v1`。
- `factor-forge-step4`
  - 明确 Step4 是 evaluation / composition consumer，不是 raw minute backfill owner。
  - 组合已有 state 可以；生产级 raw-minute derived state 构建不可以。
- `factor-forge-step6`
  - Council revision 必须输出 revision data plan。
  - 区分 formula change、state change、portfolio-only change。
- `factor-forge-researcher`
  - 每轮研究沉淀时必须记录 state reuse / missing state / data requests。

## 8. 验收建议

建议新增 smoke：

1. 已有 datamart 复用 smoke
   - law 声明依赖 `intraday_flow_state_v2`；
   - catalog 有 ACCEPT QA；
   - Step3 输出 reuse hit；
   - Step4 不扫 raw minute。

2. 缺 datamart request smoke
   - law 声明依赖不存在的 `moneyflow_xxx_state_v1`；
   - Step3 生成 `data_request_v1`；
   - Ultimate outcome 为 awaiting_data_api_request；
   - 不启动 Step4 full-window。

3. raw minute forbidden smoke
   - Step4 尝试 production full-window raw minute streaming；
   - 直接 BLOCK `BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN`。

4. portfolio-only revision smoke
   - child 只改 rebalance / holding / weighting；
   - 不重算 factor value；
   - 只重跑 Step4 evaluation。

## 9. 对架构师的结论

请把 datamart reuse 变成 Factor Forge 的显式合同，而不是研究员的习惯。

长期目标是：

```text
Raw minute -> Data API state datamart -> Factor law composition -> Step4 evaluation
```

而不是：

```text
Raw minute -> every new factor -> repeated full-window recompute
```

这样才能支持 Council 多分支探索，同时保持研究速度、lineage、QA 和可复现性。
