# Data API 当前数据与接口清单

生成时间：2026-06-25

## 一句话版

Data API 现在已经不是空壳，active catalog 里有日线主表、分钟线原始表、若干 universe/风控状态、几个 intraday state、factor library 面板和研究专用 slice。

最重要的正式主表是：

- `clean_daily_bar`：日线清洗主表，已经到 `20260624`
- `minute_bar`：1 分钟原始行情，catalog 当前到 `20260430`
- `microcap_universe` / `tradability_risk_flags_daily`：OOS 修复到 `20260612`
- `clean_daily_bar_oos_slice`：Alpha015 专用固定窗口 slice，到 `20260612`

## 现在 catalog 里有什么数据

| dataset_id | 用途 | 当前覆盖 | 状态说明 |
|---|---|---:|---|
| `clean_daily_bar` | 正式日线清洗主表，含 OHLCV、amount、pct_chg、turnover、估值、市值等字段 | `20100104-20260624` | 主力日线数据，研究需要最新日线应优先用这个 |
| `minute_bar` | Tushare 1 分钟原始行情 | `20160104-20260430` | 原始分钟数据，coverage 明显落后于日线 |
| `standard_full_market_universe` | 标准全市场股票池 | `20160104-20250711` | IS 用，尚未补到最新 OOS |
| `microcap_universe` | 微盘 Small10/Small20 股票池 | `20160104-20260612` | 已做 OOS coverage repair |
| `tradability_risk_flags_daily` | 日频可交易/风险过滤 flags | `20160104-20260612` | 用于研究侧后置过滤，不改变 raw universe |
| `index_weight_universe` | 沪深300/中证500/中证1000/中证A500/中证2000等指数成分权重 | `20160104-20260610` | 指数 universe |
| `clean_daily_bar_oos_slice` | Alpha015 / V18 OOS 固定窗口日线 slice | `20250603-20260612` | 固定窗口，不是每日滚动主表 |
| `intraday_retained_chip_state_v1` | LCR retained chip 日频状态 | `20160104-20260612` | intraday 派生状态 |
| `intraday_pseudo_dollar_bar_v1` | 由 1 分钟线构造的 pseudo dollar bar | `20160104-20250711` | IS-only；不是 tick 级真实 dollar bar |
| `factor_library_registry_bootstrap_v1` | bootstrap 因子注册表 | as_of `20260622` | 候选库，不等于官方因子库 |
| `factor_library_factor_return_panel_bootstrap_v1` | bootstrap 因子收益面板 | catalog 未填 freshness | 候选库辅助面板 |
| `factor_library_exposure_panel_bootstrap_v1` | bootstrap 因子暴露面板 | local only | catalog 标注 S3 上传曾 BLOCK，不应当成生产 S3 表 |
| `factor_library_registry_v1` | factor library registry v1 | catalog 未填 freshness | 正式三件套之一，需补 freshness/read proof |
| `factor_library_exposure_panel_v1` | factor exposure panel v1 | catalog 未填 freshness | 正式三件套之一，需补 freshness/read proof |
| `factor_library_factor_return_panel_v1` | factor return panel v1 | catalog 未填 freshness | 正式三件套之一，需补 freshness/read proof |
| `turnrate_vol_trend_penalty_feature_panel_v1` | TURNRATE_VOL_TREND_PENALTY feature panel | catalog 未填 freshness | feature candidate，不含 alpha 结论 |
| `turnrate_vol_trend_penalty_feature_return_panel_v1` | TURNRATE feature return panel | catalog 未填 freshness | feature candidate return diagnostics |

## 最重要字段

### `clean_daily_bar`

常用字段：

```text
trade_date, ts_code,
open, high, low, close, pre_close,
change, pct_chg,
vol, amount,
turnover_rate, turnover_rate_f, volume_ratio,
pe, pe_ttm, pb, ps, ps_ttm,
total_mv, circ_mv, free_float_mcap,
ln_mcap_free, ln_total_mv, ln_circ_mv
```

### `minute_bar`

常用字段：

```text
trade_date, ts_code, trade_time, bar_time, minute_index,
open, high, low, close,
vol, amount,
freq, source
```

### Universe / flags

常用字段：

```text
trade_date, ts_code, universe_id, in_universe,
market_cap, excluded_st, excluded_new_stock,
excluded_untradable, excluded_major_risk,
is_investable_core, is_investable_500m
```

## 写好了什么接口

### Python Data API

核心入口：

```python
from factor_factory.data_api.client import DataApiClient
from factor_factory.data_api.query import DataQuery

client = DataApiClient.from_default_catalog()
```

列出当前所有数据：

```python
client.list_datasets()
```

通用读取：

```python
result = client.fetch(
    DataQuery(
        dataset="clean_daily_bar",
        start_date="20260624",
        end_date="20260624",
        universe="a_share_all",
        fields=["open", "high", "low", "close", "vol", "amount", "turnover_rate", "pct_chg"],
    )
)

df = result.frame
```

便捷接口：

```python
client.get_daily_bars(start_date, end_date, universe="a_share_all", fields=None)
client.get_daily_basic(start_date, end_date, universe="a_share_all", fields=None)
client.get_minute_bars(start_date, end_date, universe="a_share_all", fields=None)
```

返回对象里有：

```text
result.frame       # pandas DataFrame
result.status      # ready / blocked / proxy_ready
result.coverage    # row_count, date_count, ticker_count, duplicate_key_count 等
result.source      # 数据来源
result.freshness   # 最新日期信息
```

### 命令行接口

列出数据：

```bash
python3 scripts/factorforge_data_api.py list
```

查看某张表：

```bash
python3 scripts/factorforge_data_api.py describe clean_daily_bar
```

抽样读取：

```bash
python3 scripts/factorforge_data_api.py sample clean_daily_bar \
  --start 20260624 \
  --end 20260624 \
  --columns ts_code,trade_date,open,high,low,close,vol,amount,turnover_rate,pct_chg \
  --limit 5
```

管理研究员数据需求：

```bash
python3 scripts/data_request_inbox.py list
python3 scripts/data_request_inbox.py status <request_id>
python3 scripts/data_request_inbox.py claim <request_id>
python3 scripts/data_request_inbox.py resolve <resolution_json>
```

## 给研究员的使用原则

1. 要最新日线，用 `clean_daily_bar`，现在到 `20260624`。
2. 要 Alpha015 这次固定 OOS 窗口，用 `clean_daily_bar_oos_slice`，窗口到 `20260612`。
3. 不要让研究员自己从 raw Tushare 生成日线主表，除非 Data API 明确 BLOCK。
4. request-specific slice 不等于日更主表；如果要滚动到最新日期，要单独刷新或改成 rolling datamart。
5. `catalog 未填 freshness` 的表可以存在，但不应当直接当成已完全交付的生产表，需要补 QA/read smoke 后再给研究正式依赖。

## 当前明显缺口

1. `minute_bar` catalog 只到 `20260430`，落后于日线。
2. `standard_full_market_universe` 只到 `20250711`。
3. 多个 factor library / feature panel 已注册，但 freshness 为空，需要补 proof。
4. `factor_library_exposure_panel_bootstrap_v1` 是 local only，catalog 里标了 S3 上传 blocked，不应被研究侧当作 S3 生产表。
5. Data API 有读接口、catalog、request inbox 工具，但还缺“每日更新后自动刷新 catalog + read smoke + proof”的强制闭环。
