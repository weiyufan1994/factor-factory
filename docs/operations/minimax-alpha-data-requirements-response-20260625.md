# MiniMax A 股 Alpha 数据需求回执

- 日期: `2026-06-25`
- 来源需求: `/Users/humphrey/Downloads/data_requirements.md`
- 处理人: `codex-data-router`
- 结论: P0 已有但覆盖区间需纠正；P1/P2 部分已有 raw/source，已提交 Data API request；P3 给出当前取法和文档位置。

## 总览

| 需求 | 状态 | 处理 |
| --- | --- | --- |
| P0 factor return panel | 已有 | 直接用 `factor_library_factor_return_panel_v1`，当前正式分区 `20250714-20260612` |
| P0 exposure panel | 已有 | 直接用 `factor_library_exposure_panel_v1`，当前正式分区 `20250714-20260612` |
| P1 行业分类 | 需要新建 | 已提交 `equity_industry_classification_daily_v1` |
| P1 复权因子 | 部分已有 | raw S3 已有，已提交 `adj_factor_daily_v1` datamart/catalog 请求 |
| P1 特殊状态股票标记 | 部分已有 | `tradability_risk_flags_daily`/universe 可先用；精确状态已提交 `equity_status_flags_daily_v1` |
| P2 龙虎榜 | 需要新建 | 已提交 `dragon_tiger_billboard_daily_v1` |
| P2 北向资金 | 需要新建 | 已提交 `northbound_holding_flow_daily_v1` |
| P2 融资融券 | 部分已有 | raw ingestion 已有 `margin/margin_detail`，已提交 `margin_trading_daily_v1` |
| P2 限售解禁 | 需要新建 | 已提交 `share_unlock_events_v1` |
| P2 股东户数 | 需要新建 | 已提交 `shareholder_count_quarterly_v1` |
| P2 公告事件 | 部分财务公告源已有 | 已提交 `corporate_event_announcement_daily_v1` |

## P0-1.1 factor_library_factor_return_panel 字段字典

- 状态: 已有
- Dataset: `factor_library_factor_return_panel_v1`
- 路径: `s3://yufan-data-lake/factorforge/datamart/factor_library_factor_return_panel/v1`
- 当前分区: `20250714-20260612`
- 对象数: `222`
- Data API read smoke: `20260610` 返回 `ready`，`6` 行

字段:

```text
trade_date, factor_id, factor_version, return_type, horizon,
holding_period, universe, factor_return, factor_return_gross,
factor_return_net, cost_model, construction_policy,
information_lag_policy, source_exposure_version, source_return_field,
no_future_exposure, label_maturity_policy,
factor_return_tstat_window, factor_return_vol_window,
factor_return_z, factor_return_rank, long_leg_return, short_leg_return,
long_only_top_bucket_excess_return, turnover, coverage_count,
effective_name_count, regression_weight_policy, neutralization_policy
```

读取示例:

```python
from factor_factory.data_api.client import DataApiClient
from factor_factory.data_api.query import DataQuery

client = DataApiClient.from_catalog(
    "/Users/humphrey/projects/factor-factory-data-api/factorforge/data/catalog/data_catalog.json"
)

result = client.fetch(DataQuery(
    "factor_library_factor_return_panel_v1",
    "20260610",
    "20260610",
    "a_share_all",
    ["factor_id", "factor_version", "return_type", "horizon", "universe", "factor_return", "long_leg_return", "turnover"],
    frequency="daily",
    allow_duplicate_keys=True,
))
print(result.status, result.frame.head())
```

备注:

- 这个 panel 是 OOS/近期评估面板，不是 2015 起全历史面板。
- 如果 minimax 需要 2015 起全历史 factor return，需要另提 backfill，不要误用当前 OOS panel 当全历史。

## P0-1.2 factor_library_exposure_panel 完整字段清单

- 状态: 已有
- Dataset: `factor_library_exposure_panel_v1`
- 路径: `s3://yufan-data-lake/factorforge/datamart/factor_library_exposure_panel/v1`
- 当前分区: `20250714-20260612`
- 对象数: `222`
- Data API read smoke: `20260610` 返回 `ready`，`10009` 行

字段:

```text
trade_date, ts_code, factor_id, factor_version, factor_value_raw,
factor_value_z, factor_rank, factor_direction, standardization_scope,
universe_policy, information_date, effective_trade_date, no_future_data,
source_artifact_path, factor_value_identity_hash,
factor_value_winsorized, factor_value_neutralized,
neutralization_policy, industry_neutralized, size_neutralized,
liquidity_neutralized, missing_value_policy, tradability_policy,
is_official_factor, is_candidate_feature, is_state_diagnostic
```

读取示例:

```python
result = client.fetch(DataQuery(
    "factor_library_exposure_panel_v1",
    "20260610",
    "20260610",
    "a_share_all",
    ["factor_id", "factor_version", "factor_value_raw", "factor_rank", "industry_neutralized", "is_candidate_feature", "is_official_factor"],
    frequency="daily",
    allow_duplicate_keys=True,
))
print(result.status, result.frame.head())
```

因子列表:

- Dataset: `factor_library_registry_v1`
- 路径: `s3://yufan-data-lake/factorforge/datamart/factor_library_registry/v1/factor_library_registry.parquet`
- 字段:

```text
factor_id, factor_version, factor_name, factor_family, library_status,
direction, horizon, holding_period, source_report_id, implementation_mode,
formula_or_law_hash, exposure_dataset_version, return_dataset_version,
admission_status, admission_date, owner
```

读取注意:

- registry 是静态单文件，没有 `trade_date`；不要用 `DataQuery` 日期过滤。
- 直接读 parquet，或先 `aws s3 cp` 到本地再 `pd.read_parquet`。

## P1-2.1 行业分类

- 状态: 需要新建
- 已提交 Data API request:
  `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__equity_industry_classification_daily_v1__20260625.json`
- 请求 dataset: `equity_industry_classification_daily_v1`
- 目标字段:

```text
trade_date, ts_code, industry_standard,
ind_l1_code, ind_l1_name, ind_l2_code, ind_l2_name,
ind_l3_code, ind_l3_name, source_effective_date
```

备注:

- 当前 active catalog 没有正式行业时间序列。
- `clean_daily_bar` 请求 `industry_code` 会 BLOCK，这是已知缺口。

## P1-2.2 复权因子

- 状态: 部分已有，缺 datamart/catalog
- raw S3: `s3://yufan-data-lake/tushares/行情数据/adj_factor.csv`
- raw 文件状态: `2026-06-24 22:22:17`，约 `365,892,783` bytes
- 已提交 Data API request:
  `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__adj_factor_daily_v1__20260625.json`
- 请求 dataset: `adj_factor_daily_v1`
- 目标字段:

```text
trade_date, ts_code, adj_factor, forward_factor, backward_factor
```

备注:

- `clean_daily_bar` catalog metadata 写的是 `adjust_mode=forward`，其 OHLC 已按共享清洗 policy 处理。
- minimax 如果要自己做复权对照，等 `adj_factor_daily_v1` 注册后再通过 Data API 取；不要在研究侧反复下载 366MB CSV。

## P1-2.3 特殊状态股票标记

- 状态: 部分已有
- 现可用 dataset: `tradability_risk_flags_daily`
- 路径: `s3://yufan-data-lake/factorforge/datamart/tradability_risk_flags_daily/v1`
- 覆盖: `20160104-20260612`
- 字段:

```text
trade_date, ts_code, market_cap, market_cap_source,
excluded_small_cap, excluded_st, excluded_new_stock,
excluded_untradable, excluded_major_risk,
is_investable_core, is_investable_500m
```

读取示例:

```python
result = client.fetch(DataQuery(
    "tradability_risk_flags_daily",
    "20260610",
    "20260610",
    "a_share_all",
    ["excluded_st", "excluded_new_stock", "excluded_untradable", "excluded_major_risk", "is_investable_core"],
    frequency="daily",
))
```

精确字段缺口:

- `is_star_st`
- `is_suspended`
- `is_delisted`
- `listed_days`
- `trade_status`

已提交 Data API request:
`/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__equity_status_flags_daily_v1__20260625.json`

## P2 请求状态

以下都已提交到 Data API inbox，当前不是 active catalog:

| 需求 | request path |
| --- | --- |
| 龙虎榜 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__dragon_tiger_billboard_daily_v1__20260625.json` |
| 北向资金 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__northbound_holding_flow_daily_v1__20260625.json` |
| 融资融券 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__margin_trading_daily_v1__20260625.json` |
| 限售解禁 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__share_unlock_events_v1__20260625.json` |
| 股东户数 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__shareholder_count_quarterly_v1__20260625.json` |
| 公告事件 | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/data_request__MINIMAX_ALPHA_DATA_REQUIREMENTS_20260625__corporate_event_announcement_daily_v1__20260625.json` |

备注:

- `margin` / `margin_detail` 在 raw ingestion specs 里已经有支持，但没有 active datamart/catalog，所以按“raw 部分已有、研究 datamart 待准备”处理。
- `forecast_vip` / `express_vip` / `disclosure_date` 在财务 raw access 里已有线索，但公告事件统一表仍需 datamart 化。

## P3 基础设施回答

### 私有包 / 官方接口

当前可用的是本地 repo:

```text
/Users/humphrey/projects/factor-factory-data-api
```

Python import:

```python
from factor_factory.data_api.client import DataApiClient
from factor_factory.data_api.query import DataQuery
```

临时使用:

```bash
export PYTHONPATH=/Users/humphrey/projects/factor-factory-data-api:$PYTHONPATH
```

或在该 repo 下 editable install。`pyproject.toml` 的 package name 当前是 `factor-factory`，不是 `factorforge_data_api`。

### Datamart 字典

当前已有草稿:

```text
/Users/humphrey/projects/factor-factory-data-api/docs/data-api-data-dictionary.zh-CN.md
```

active catalog:

```text
/Users/humphrey/projects/factor-factory-data-api/factorforge/data/catalog/data_catalog.json
```

### OOS 切分

Factor Forge 研究默认约束:

```text
full_is = 2016-01-01 .. 2025-07-11
protected_oos = 2025-07-14 onward
```

当前 `clean_daily_bar_oos_slice`:

```text
dataset = clean_daily_bar_oos_slice
path = s3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1
coverage = 20250603 .. 20260612
research_scope = fixed_oos_slice_for_v18_incremental_eval
```

注意: `clean_daily_bar_oos_slice` 比 protected OOS 多带一段 pre-OOS buffer，不应把 `20250603-20250711` 当测试集。

### QuantGPT / operator 文档

目前没有看到一份完整的 QuantGPT operator 清单。可参考:

```text
/Users/humphrey/projects/factor-factory-data-api/factor_factory/data_api/intraday_operator_kernels.py
/Users/humphrey/projects/factor-factory-data-api/tests/test_intraday_operator_kernels.py
/Users/humphrey/projects/factor-factory-data-api/docs/operations/minute-factor-acceleration-roadmap-20260616.zh-CN.md
```

但这主要覆盖 intraday operator backend，不等价于 WQ101/QuantGPT 表达式全集。`indneutralize` 仍然依赖行业数据补齐。

## 已准备的数据请求清单

```text
equity_industry_classification_daily_v1
adj_factor_daily_v1
equity_status_flags_daily_v1
dragon_tiger_billboard_daily_v1
northbound_holding_flow_daily_v1
margin_trading_daily_v1
share_unlock_events_v1
shareholder_count_quarterly_v1
corporate_event_announcement_daily_v1
```

全部 request 已通过 `scripts/data_request_inbox.py validate`。
