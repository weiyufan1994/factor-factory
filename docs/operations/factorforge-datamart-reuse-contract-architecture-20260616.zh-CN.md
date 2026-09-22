# Factor Forge Datamart / State Reuse 合同架构书

日期：2026-06-16

状态：架构师方案，待实现

对象：Factor Forge Ultimate / Step3 / Step4 / Step6 / coder / reviewer

依据：

- 研究员反馈：`docs/operations/factorforge-skill-feedback-datamart-reuse-contract-20260616.zh-CN.md`
- 数据组反馈：`docs/operations/data-api-datamart-production-performance-feedback-20260616.zh-CN.md`
- 既有架构：`docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`
- 既有隔离合同：`docs/operations/factorforge-factor-research-workspace-architecture-20260612.zh-CN.md`

## 1. 结论

Factor Forge 需要新增 P0 级 `state datamart reuse contract`。

当前 Factor Forge 已经有 factor workspace 隔离、Step3 data readiness、Step4 evaluation、Step6 Council revision 等能力，但这些能力还没有把可复用 state datamart 变成显式执行合同。因此 Council 每轮生成新 law 后，系统容易把“factor value 应该重算”和“raw minute derived state 也要重建”混在一起。

正确边界是：

```text
Raw minute / raw daily
  -> Data API state datamart
  -> Factor law composition
  -> Step4 evaluation
```

而不是：

```text
Raw minute
  -> every new factor revision
  -> repeated full-window recompute
```

Factor formula / law 的变化通常需要重算 `factor_values`，这是合理的；但 cutoff flow、distribution moments、occupation measure、daily basic controls、tradability、universe、pseudo dollar bar 等 state variables 应先通过 Data API catalog 解析，已有且 QA ACCEPT 的必须复用，缺失时必须生成 `data_request_v1` 并 BLOCK。

## 2. 本架构只负责什么

本架构只解决 Factor Forge skill/framework 层：

1. factor law 如何声明依赖哪些 state datamart；
2. Step3 如何 catalog-first 解析 state dependency；
3. 缺 state 时如何生成 `data_request_v1` 并停止正式执行；
4. Step4 如何证明自己只消费 datamart，不做 production full-window raw minute 扫描；
5. Step6 / Council 如何在 revision 中输出 data plan；
6. Ultimate 如何 gate 整个 workflow。

本架构不负责：

1. 不生产 Data API datamart；
2. 不决定 Data API parquet partition / Polars / DuckDB / shard 调度实现；
3. 不启动 clean data、search worker、production Step3B/Step4/Step6；
4. 不评价 Moneyflow V20 因子有效性；
5. 不迁移历史 datamart；
6. 不把 alpha score / composite research feature 推入 Data API P0 schema。

Data API 侧只作为外部依赖：Factor Forge 要求 Data API catalog 能回答 dataset 是否存在、schema 是否匹配、coverage 是否足够、QA 是否 ACCEPT、lookahead policy 是否完整。

## 3. 核心设计原则

### 3.1 Factor value 重算与 state datamart 重建必须分离

每轮 Council revision 可能改变：

- formula / law；
- weighting / gate / nonlinear transform；
- state variable dependency；
- portfolio policy；
- holding / rebalance policy。

只有新增缺失 state variable 时，才应进入 Data API request。只改权重、gate、portfolio policy 或组合方式时，不应触发 raw minute full-window data engineering。

### 3.2 Step3 是 state dependency resolver

Step3 不只是生成 data readiness 文档，它必须成为执行前的数据依赖解析层：

1. 读取 executable law / child spec 中的 `state_dependency_contract`；
2. 查询 Data API catalog 或本地 mock registry；
3. 输出 `state_resolution`；
4. 对缺失、未 QA、schema mismatch、coverage 不足、lookahead policy 缺失直接 BLOCK；
5. 必要时写 `data_request_v1`。

### 3.3 Step4 是 datamart consumer，不是 raw-minute backfill owner

Step4 可以：

- 读取已 ACCEPT 的 state datamart；
- 做 factor law composition；
- 做 bounded smoke；
- 做 evaluation / backtest / portfolio comparison；
- 记录 load seconds 和 reuse provenance。

Step4 不可以：

- 在 production full-window 路径临时扫多年 raw minute；
- 将 bounded smoke 伪装成 full-window proof；
- 在缺 state datamart 时自行 fallback 到 raw minute；
- 直接猜 Data API / S3 路径绕过 catalog。

### 3.4 Council revision 必须输出 data plan

Step6 / Council 不能只输出新公式，还必须说明该 revision 对数据层的影响：

| Revision 类型 | 是否重算 factor value | 是否需要 Data API request | 动作 |
|---|---:|---:|---|
| 只改权重 / transform / gate | 是 | 否 | 复用已有 state，重算 factor value |
| 新增已有 datamart 字段 | 是 | 否 | Step3 catalog reuse |
| 新增未注册 state variable | 否或 bounded smoke | 是 | 写 `data_request_v1`，正式流程 BLOCK |
| 需要新 raw data | 否 | 是 | BLOCK 成 Data API request |
| 只改 portfolio / rebalance / holding | 否 | 否 | 不重算 factor value，只重跑 Step4 evaluation |

## 4. State Dependency Contract

每个 executable law、child spec、direct-code spec 应新增：

```json
{
  "state_dependency_contract": {
    "contract_version": "factorforge_state_dependency_contract_v1",
    "required_datasets": [
      {
        "dataset_id": "intraday_flow_state_v2",
        "schema_version": "intraday_flow_state_v2_schema_v2.1",
        "window": {
          "start": "20160104",
          "end": "20250711"
        },
        "required_fields": ["flow_z", "large_flow_z", "ret_1450"],
        "parameters": {
          "cutoff_time": "14:50:00"
        },
        "qa_required": true,
        "lookahead_policy_required": true,
        "no_future_intraday_minutes": true
      }
    ],
    "allowed_missing_behavior": "block",
    "raw_minute_full_window_allowed": false,
    "bounded_smoke_allowed": true,
    "data_request_on_missing": true
  }
}
```

字段语义：

- `required_datasets`：Factor law 依赖的 state datamart 列表。
- `schema_version`：可为空，但生产 formal run 推荐必填；为空时 Step3 至少要记录 catalog 返回的 active schema。
- `required_fields`：Step4 实际需要读取的字段，用于 projection 和 schema guard。
- `parameters`：cutoff、lookback、binning、threshold table 等参数。
- `qa_required`：生产路径必须为 true。
- `lookahead_policy_required`：分钟状态默认必须为 true。
- `raw_minute_full_window_allowed`：默认 false；只有人工显式批准的数据生产任务才可能 true。
- `bounded_smoke_allowed`：允许小样本公式 smoke，但 smoke 不能作为 production proof。
- `data_request_on_missing`：缺失时由 Step3 写 `data_request_v1`。

Data API catalog resolver 必须兼容真实生产 fragment，而不是只兼容
synthetic smoke。至少支持：

- fields 来自 `fields`、`schema` 或 `columns`；
- schema version 来自顶层 `schema_version` 或 `metadata.schema_version`；
- QA path 来自 `qa_path`、`qa_summary_path` 或 `metadata.qa_summary_path`；
- lookahead/no-future policy 来自结构化 `lookahead_policy`，或
  `no_future_intraday_minutes=true/"true"`；
- materialized root 来自 `materialized_root`、`root`、`source_uri` 或 `uri`。

如果 production QA verdict 不在 catalog 内，resolver 应通过 QA summary
path 读取 verdict；读不到时不能默认为 ACCEPT。

## 5. Step3 State Resolution 合同

Step3 输出路径应落在 factor workspace 内，例如：

```text
factor_research/<factor_id>/<research_id>/objects/data_prep_master/<report_id>/
  state_resolution__<report_id>.json
  data_request__<request_id>.json
```

`state_resolution` schema：

```json
{
  "contract_version": "factorforge_state_resolution_v1",
  "report_id": "...",
  "factor_id": "...",
  "research_id": "...",
  "resolved_at_utc": "...",
  "dependency_contract_path": "...",
  "catalog_source": {
    "type": "data_api_catalog",
    "path_or_uri": "..."
  },
  "reuse_hits": [
    {
      "dataset_id": "intraday_flow_state_v2",
      "schema_version": "intraday_flow_state_v2_schema_v2.1",
      "catalog_entry_path": "...",
      "qa_path": "...",
      "qa_verdict": "ACCEPT",
      "coverage": {
        "start": "20160104",
        "end": "20250711"
      },
      "required_fields_present": true,
      "lookahead_policy_present": true,
      "materialized_root": "s3://..."
    }
  ],
  "state_dependencies_required": true,
  "no_state_required": false,
  "missing_state_variables": [],
  "data_request_ids": [],
  "blocked": false,
  "blocker_token": null
}
```

不依赖 derived state 的普通日频因子也必须写显式 no-op resolution：

```json
{
  "contract_version": "factorforge_state_resolution_v1",
  "reuse_hits": [],
  "state_dependencies_required": false,
  "no_state_required": true,
  "blocked": false
}
```

这表示 Step4 可以继续使用普通 Data API / daily contract，不表示跳过
state reuse guard。

缺失时必须写 `data_request_v1`：

```json
{
  "contract_version": "factorforge_data_request_v1",
  "request_id": "data_request__<report_id>__<dataset_id>",
  "request_type": "state_datamart_missing",
  "dataset_id": "moneyflow_v20_slow_state_v1",
  "required_schema_version": "...",
  "required_fields": [],
  "required_coverage": {
    "start": "20160104",
    "end": "20250711"
  },
  "parameters": {},
  "lookahead_policy_required": true,
  "consumer": {
    "factor_id": "...",
    "research_id": "...",
    "report_id": "..."
  },
  "status": "requested",
  "production_execution_allowed": false
}
```

## 6. Step4 Provenance 合同

Step4 必须在 evaluation metadata 或 performance profile 中写：

```json
{
  "state_datamart_reuse": {
    "contract_version": "factorforge_state_datamart_reuse_v1",
    "state_resolution_path": "...",
    "reuse_hit": true,
    "datasets": [
      {
        "dataset_id": "intraday_flow_state_v2",
        "schema_version": "intraday_flow_state_v2_schema_v2.1",
        "fields_read": ["flow_z", "large_flow_z"],
        "materialized_root": "s3://...",
        "load_seconds": 12.3
      }
    ],
    "raw_minute_full_window_scan": false,
    "bounded_smoke": false
  }
}
```

Production Step4 必须拒绝以下情况：

1. `state_resolution.blocked == true`；
2. 缺少 `state_resolution_path`；
3. 需要的 dataset 没有 QA ACCEPT；
4. `raw_minute_full_window_scan == true` 且没有人工批准的数据生产上下文；
5. Step4 发现输入来自 raw minute root 而非 catalog datamart root。

## 7. Step6 / Council Revision Data Plan

Council synthesis、multibranch synthesis、child executable revision spec 必须包含：

```json
{
  "revision_data_plan": {
    "contract_version": "factorforge_revision_data_plan_v1",
    "reuse_existing_state": true,
    "new_state_required": false,
    "data_request_required": false,
    "portfolio_only_revision": false,
    "factor_value_recompute_required": true,
    "required_datasets": ["intraday_flow_state_v2"],
    "new_state_candidates": [],
    "raw_minute_full_window_allowed": false,
    "reason": "revision only changes nonlinear transform over existing state"
  }
}
```

如果 Council 提出新增 state variable，必须进入以下二选一：

1. bounded smoke：只证明公式/字段/shape，不进入 production full-window；
2. data request：由 Step3 写 `data_request_v1`，Ultimate outcome 为 awaiting data。

## 8. Ultimate Gate

Ultimate formal run 在进入 Step4 前必须检查：

```text
factor workspace exists
runtime context v2 valid
state_dependency_contract exists
state_resolution exists
state_resolution.blocked == false
all required datasets QA ACCEPT
raw_minute_full_window_allowed == false for Step4 production
```

缺失任一项必须 BLOCK，不允许 silently fallback。

## 9. Blocker Tokens

新增或标准化以下 tokens：

```text
BLOCK_FACTORFORGE_STATE_DEPENDENCY_UNDECLARED
BLOCK_FACTORFORGE_STATE_RESOLUTION_MISSING
BLOCK_FACTORFORGE_STATE_DATAMART_MISSING
BLOCK_FACTORFORGE_STATE_DATAMART_QA_NOT_ACCEPTED
BLOCK_FACTORFORGE_STATE_SCHEMA_VERSION_MISMATCH
BLOCK_FACTORFORGE_STATE_COVERAGE_INSUFFICIENT
BLOCK_FACTORFORGE_STATE_LOOKAHEAD_CONTRACT_MISSING
BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED
BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN
BLOCK_FACTORFORGE_STATE_REUSE_PROVENANCE_MISSING
```

这些 token 的目标是阻止伪生产，而不是阻止研究。bounded smoke 可以继续跑，但必须标记为 smoke，不能替代 full-window proof。

## 10. Skill 文档改造点

### factor-forge-ultimate

新增：

- formal run 必须先通过 state dependency resolution；
- Step4 前必须读取 `state_resolution`；
- 缺 datamart 时 outcome 为 awaiting data request；
- production raw minute full-window scan 默认 forbidden。

### factor-forge-step3

新增：

- 从 law / child spec 解析 `state_dependency_contract`；
- catalog-first lookup；
- 写 `state_resolution_v1`；
- 缺失或不合格写 `data_request_v1` 并 BLOCK。

### factor-forge-step4

新增：

- Step4 只消费 ACCEPT datamart 或 bounded smoke input；
- production full-window raw minute scan forbidden；
- 写 `state_datamart_reuse_v1` provenance。

### factor-forge-step6

新增：

- Council synthesis 必须输出 `revision_data_plan_v1`；
- 区分 formula revision、state revision、portfolio-only revision；
- 新 state 不直接进入 production run。

### factor-forge-researcher

新增：

- 每轮研究 closeout 记录 state reuse / missing state / data request；
- 不把 alpha score 推给 Data API P0 schema。

## 11. Knowledge Reference 合同

Step1 / Step2 / Step6 参考因子知识库必须从“软约定”升级为可审计合同。

`knowledge_reference_contract` schema：

```json
{
  "contract_version": "factorforge_knowledge_reference_contract_v1",
  "producer": "step1_research_discipline",
  "retrieval_required": false,
  "retrieval_status": "retrieved|cold_start",
  "query_hash": "...",
  "query_terms": ["..."],
  "index_paths_checked": [".../knowledge/retrieval/factorforge_retrieval_index.jsonl"],
  "indexes_available": ["..."],
  "hit_count": 1,
  "retrieved_case_ids": ["knowledge_record__..."],
  "similar_case_lessons_imported": ["..."],
  "fallback_reason": null
}
```

规则：

1. Step1 必须写 `knowledge_reference_contract`，并保持
   `similar_case_lessons_imported` 来自该合同。
2. Step2 必须原样保留该合同到 `research_contract` 和
   `learning_and_innovation`，不能只保留一段 lesson 文本。
3. Step6 / Council 每次 revision 必须写 retrieval context；没有命中时必须
   记录 cold-start knowledge gap。
4. formal validator 不要求知识库一定有命中，但必须要求 provenance 完整。

新增 blocker：

- `BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING`
- `BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_INDEX_MISSING`
- `BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_REQUIRED`
- `BLOCK_FACTORFORGE_REVISION_KNOWLEDGE_CONTEXT_MISSING`

## 12. 验收 Smoke

必须新增 smoke，不启动真实 worker，不跑 full-window production：

1. `state_reuse_hit_smoke`
   - law 声明依赖 `intraday_flow_state_v2`；
   - fake catalog 中 QA 为 ACCEPT；
   - Step3 输出 reuse hit；
   - Step4 provenance 标记 `raw_minute_full_window_scan=false`。

2. `state_missing_data_request_smoke`
   - law 声明依赖不存在的 `moneyflow_xxx_state_v1`；
   - Step3 写 `data_request_v1`；
   - Ultimate dry-run outcome 为 awaiting data request；
   - 不启动 Step4 production。

3. `raw_minute_forbidden_smoke`
   - 模拟 Step4 production 输入来自 raw minute root；
   - 直接 BLOCK `BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN`。

4. `portfolio_only_revision_smoke`
   - Council child 只改 holding / rebalance；
   - `factor_value_recompute_required=false`；
   - 不触发 Step3B factor value recompute。

5. `state_schema_coverage_negative_smoke`
   - fake catalog dataset 存在但 schema 或 coverage 不满足；
   - BLOCK 对应 schema / coverage token。

6. `real_data_api_catalog_fragment_smoke`
   - 使用真实 Data API catalog fragment；
   - resolver 能读取 `columns`、`metadata.schema_version`、
     `metadata.no_future_intraday_minutes` 和 `uri`；
   - 不应误报 schema mismatch。

7. `step3_noop_state_contract_smoke`
   - 无 derived state dependency 的日频因子写 no-op
     `state_dependency_contract` / `state_resolution`；
   - Step4 provenance 接受 `no_state_required=true`。

8. `knowledge_reference_contract_smoke`
   - 检索命中时写 hit provenance；
   - cold-start 时写 fallback reason；
   - required retrieval 且 zero-hit 时 BLOCK。

## 13. 与 Data API 的接口边界

Factor Forge 只消费 Data API 给出的 catalog closeout，不生产正式 datamart。Data API 最少要提供：

```json
{
  "dataset_id": "...",
  "schema_version": "...",
  "producer_version": "...",
  "materialized_root": "s3://...",
  "qa_verdict": "ACCEPT",
  "qa_path": "...",
  "coverage": {
    "start": "YYYYMMDD",
    "end": "YYYYMMDD"
  },
  "schema": [],
  "lookahead_policy": {},
  "deprecated": false
}
```

如果 Data API 尚未提供真实 catalog，Factor Forge 可先实现本地 fake catalog smoke，但 production run 必须要求真实 catalog 或明确的 legacy override。

## 13. 实施顺序

建议分三阶段：

1. P0 framework guard
   - contract parser；
   - fake catalog resolver；
   - Step3 state resolution；
   - Step4 raw minute forbidden guard；
   - smoke。

2. P1 Council / skill integration
   - Step6 revision data plan；
   - Ultimate gate；
   - skill 文档更新。

3. P2 Data API integration
   - 对接真实 Data API catalog；
   - 将 Data API closeout proof 变成 Step3 可消费对象；
   - 增加 read-smoke / QA provenance。

## 14. 架构结论

这次改造的目标不是让 Factor Forge 自己生产所有 datamart，而是让 Factor Forge 停止把 datamart reuse 当成人的习惯。

正式执行合同应变成：

```text
law declares state dependency
-> Step3 resolves catalog
-> ACCEPT datamart reused or data_request_v1 blocks
-> Step4 composes factor value without raw full-window scan
-> Step6 records what state was reused and what data is still missing
```

这样 Council 才能安全地进行多分支探索，同时保持研究速度、lineage、QA 和可复现性。
