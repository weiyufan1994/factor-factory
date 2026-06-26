# Alpha015 clean_daily_bar_oos_slice 数据反馈书

生成时间：2026-06-25 10:11 CST

## 结论

研究员反馈“缺数据”不是因为 Tushare raw 日更完全没有跑，而是 Data API 交付链路存在两个断点：

1. `clean_daily_bar` 主清洗层已经更新到 `20260624`，但 active catalog freshness 之前仍停在旧值，导致研究侧看 catalog 会误判为数据陈旧。
2. `clean_daily_bar_oos_slice` 是为 Alpha015 request 交付的固定 OOS slice，需求窗口截止 `20260612`，不是每日滚动更新表。

截至本反馈生成时，2026-06-25 仍在盘中，完整日线可合理使用的最新交易日是 `20260624`，不是 `20260625`。

## 已核验证据

### clean_daily_bar 主表

- S3 path: `s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet`
- S3 meta: `s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.meta.json`
- S3 object 写入时间：`2026-06-24 22:40 CST`
- parquet 实际覆盖：
  - rows: `11760204`
  - trade_date min: `20100104`
  - trade_date max: `20260624`
  - unique trade_dates: `3998`
  - tickers: `5186`
- Data API read smoke:
  - dataset: `clean_daily_bar`
  - date: `20260624`
  - status: `ready`
  - rows: `4475`
  - duplicate_key_count: `0`
  - missing_fields: `[]`

### raw Tushare 增量层

以下上游分区均已存在到 `20260624`：

- `s3://yufan-data-lake/tushares/行情数据/daily_incremental/trade_date=20260624/`
- `s3://yufan-data-lake/tushares/行情数据/daily_basic_incremental/trade_date=20260624/`
- canonical `daily.csv` S3 object 更新时间：`2026-06-24 22:20 CST`

### Alpha015 request

- request_id: `ALPHA015_SWEEP_TURNPEN_A040_20160101__clean_daily_bar_oos_slice__20260625013839`
- request status: `ACCEPT`
- fixed slice S3 path: `s3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1`
- proof: `s3://yufan-data-lake/factorforge/proofs/clean_daily_bar_oos_slice/v1/proof.json`
- resolution proof: `s3://yufan-data-lake/factorforge/proofs/clean_daily_bar_oos_slice/v1/data_request_resolution__ALPHA015_SWEEP_TURNPEN_A040_20160101__clean_daily_bar_oos_slice__20260625013839.json`
- fixed slice coverage:
  - trade_date min: `20250603`
  - trade_date max: `20260612`
  - rows: `1139752`
  - trade_dates: `251`
  - duplicate_key_count: `0`

该 slice 停在 `20260612` 的原因是研究员原始 request 明确要求覆盖 `20250601-20260612`，其中 OOS 是 `20250714-20260612`。这不是日更主表，也不应被理解为“全市场日线只更新到 6 月 12 日”。

## 这次已修复

1. 已把 Alpha015 request 从 `PENDING` 闭环为 `ACCEPT`。
2. 已在 worker `i-02cc0b6e93856fbb4` 的 PR14 runner 目录执行 true worker read smoke。
3. 已同步 `clean_daily_bar_oos_slice` catalog 到 worker runner 目录，解决 runner 本地缺 catalog 的问题。
4. 已修正本仓库 active catalog 中 `clean_daily_bar` freshness：
   - `trade_date_max=20260624`
   - `rows=11760204`
   - `tickers=5186`
   - `trade_dates=3998`
5. 已上传修正后的 active catalog 到：
   `s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json`

## 对研究侧的使用建议

如果研究任务只需要 Alpha015 PR14 request 的固定 OOS 窗口，应使用：

```text
dataset_id = clean_daily_bar_oos_slice
window = 20250603-20260612
```

如果研究任务需要日更后的最新完整交易日，应使用：

```text
dataset_id = clean_daily_bar
latest_complete_trade_date = 20260624
```

研究侧不需要自行从 raw Tushare 生成日线数据；应通过 Data API 读取 active catalog 中的 `clean_daily_bar` 或已验收的 request-specific datamart。

## 日更链路问题与整改项

这次暴露的问题不是 raw 日更本身，而是日更后缺少强制发布闭环。以后每日更新必须至少包含以下验收步骤：

1. raw `daily_incremental` / `daily_basic_incremental` 更新到最新完整交易日。
2. canonical `daily.csv` merge 并上传。
3. `clean_daily_bar` 增量 append 或 rebuild，并上传 parquet/meta。
4. active Data API catalog freshness 同步更新。
5. S3 active catalog 同步更新。
6. 对最新完整交易日运行 Data API read smoke。
7. 若存在 request-specific slice，要明确它是 fixed window 还是 rolling window；fixed window 不自动跟随日更。

## 后续动作

P0：

- 把 `refresh_clean_daily_after_tushare_update.py` 的收尾阶段改为强制刷新 active catalog，并上传到 S3 canonical catalog path。
- 增加每日 freshness proof：记录 raw max、clean max、catalog max、read smoke date、duplicate_key_count。
- 每日任务如果 clean max 与 catalog max 不一致，应标记为失败，不允许报告“日更完成”。

P1：

- 对 `clean_daily_bar_oos_slice` 明确命名或 metadata：`fixed_window=true`，避免被误认为 rolling daily dataset。
- 若研究侧需要 Alpha015 使用 `20260624`，新建或刷新 rolling OOS slice，而不是复用 `20250603-20260612` fixed slice。
