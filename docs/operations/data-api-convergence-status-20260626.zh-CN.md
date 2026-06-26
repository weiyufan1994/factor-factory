# Data API 收敛状态说明

生成时间：2026-06-26

## 结论

本次收敛后，Data API 的三类事实来源分工如下：

1. S3 是生产数据和 active catalog 的真相。
2. GitHub 保存 Data API 代码、脚本、测试、runbook 和 catalog 生成/校验规则。
3. Mac 本地只作为开发/操作工作区，不再作为研究侧读取生产数据的权威来源。

## 已收敛项

### S3 active catalog

已将 Mac 本地 active catalog 上传到：

```text
s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json
```

校验证据：

```text
local sha256 = a585262426c323c39eae0ca2c31c1945739609b7e9e87c0cd54638d1b50c7086
S3    sha256 = a585262426c323c39eae0ca2c31c1945739609b7e9e87c0cd54638d1b50c7086
```

当前 active catalog：

- dataset_count: `17`
- `clean_daily_bar.trade_date_max=20260624`
- `standard_full_market_universe.uri=s3://yufan-data-lake/factorforge/datamart/standard_full_market_universe/v1`
- 包含 TURNRATE feature panels:
  - `turnrate_vol_trend_penalty_feature_panel_v1`
  - `turnrate_vol_trend_penalty_feature_return_panel_v1`

### GitHub

GitHub 不跟踪 `factorforge/data/catalog/data_catalog.json`。该文件在 `.gitignore` 中被 `factorforge/` 屏蔽，这是有意边界：active catalog 是运行产物，应发布到 S3，不应作为 repo 代码真相。

本次 GitHub 收敛提交范围：

- Data API package 代码
- Data API backend/CLI/read smoke/request inbox 工具
- datamart builder/validator/closeout 脚本
- tests
- operations runbook / inventory / feedback docs
- `.gitignore` 增加 `.cache/`，避免 parquet 缓存误入 Git

不提交：

- `factorforge/` 下的运行数据、active catalog、本地 resolved request 文件
- `.cache/` parquet 缓存
- S3 parquet 数据本体

## 当前权威读取方式

研究侧和 worker 应读取：

```text
s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json
```

如果本地运行 Data API，要么显式下载这份 S3 catalog，要么设置：

```text
FACTORFORGE_DATA_CATALOG=<downloaded data_catalog.json>
```

不要把 GitHub 中是否存在 `factorforge/data/catalog/data_catalog.json` 当作数据可用性的判断标准。

## 仍未完全收敛的风险

1. 部分 catalog entries 的 `freshness` 仍为空，需要逐个补 QA/read smoke proof。
2. `minute_bar` catalog 最新日期仍落后于日线。
3. 日更链路仍需要把“更新 parquet/meta -> 更新 S3 active catalog -> read smoke -> proof”做成强制闭环。
4. 若 worker 使用 repo-local default catalog，必须在任务启动前从 S3 同步 active catalog。

## 后续规则

每日更新完成标准必须同时满足：

1. S3 数据对象已更新。
2. S3 active catalog 已更新。
3. 最新完整交易日 read smoke 通过。
4. proof 写入 S3。
5. worker/research runner 不依赖 Mac 本地 catalog。
