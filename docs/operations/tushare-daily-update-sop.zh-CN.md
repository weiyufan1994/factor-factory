# Tushare 日更 SOP

## 目标

把 `daily / daily_basic / 基础信息 / canonical daily.csv merge / shared clean daily layer` 固定成一条稳定日更链路，避免以后再靠临时命令手工拼装。

## 当前数据分层

1. `tushares/基础数据/`
   - `stock_basic.csv`
   - `trade_cal.csv`
   - `stock_st.csv`
   - `stock_st_daily_20160101_current.csv`
2. `tushares/行情数据/daily_incremental/trade_date=YYYYMMDD/`
   - 单日 `daily` 增量分区
3. `tushares/行情数据/daily_basic_incremental/trade_date=YYYYMMDD/`
   - 单日 `daily_basic` 分区
4. `tushares/行情数据/daily.csv`
   - canonical 主表
5. `data/clean/daily_clean.parquet`
   - Factor Forge 共享清洗层
   - 合并 `daily_basic` 增强字段，包括 `free_float_mcap / ln_mcap_free / total_mv / circ_mv / turnover_rate / pe / pb / ps`

## 固定顺序

每天按下面顺序执行：

1. 刷新基础表
2. 补 `daily_incremental`
3. 触发 `daily_basic_incremental`
4. 把 `daily_incremental` merge 回 canonical `daily.csv`
5. 本地按需同步到 `~/.qlib/raw_tushare/...`
6. 按需刷新 `data/clean/daily_clean.parquet`
7. 把 `daily_basic` 增强字段 merge 回 `daily_clean.parquet`

## 运行环境

- EC2 实例：`i-01c0ceb9c04ae270e`
- 远端目录：`/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取`
- 推荐 Python：`/home/ubuntu/miniconda3/envs/rdagent/bin/python`

## 每日执行入口

数据更新是授权维护动作，不是 Bernard/Humphrey researcher agent 的常规研究动作。所有会写 raw/cache/clean/canonical 的命令都必须带：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved ... --operator codex
```

本仓库本地入口：

```bash
cd /Users/humphrey/projects/factor-factory
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/run_tushare_daily_update_via_ssm.py \
  --operator codex \
  --end-date YYYYMMDD \
  --refresh-clean-layer
```

如果当天还不想立刻覆盖 `S3` 上 canonical `daily.csv`，可以先跳过 merge：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/run_tushare_daily_update_via_ssm.py \
  --operator codex \
  --end-date YYYYMMDD \
  --refresh-clean-layer \
  --skip-merge
```

如果确认要把 merge 后的 canonical `daily.csv` 回传到 `S3`，必须显式授权并 opt-in 上传：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/run_tushare_daily_update_via_ssm.py \
  --operator codex \
  --end-date YYYYMMDD \
  --refresh-clean-layer \
  --merge-upload
```

## 每一步的职责

### 1. 基础表刷新

固定刷新这四张：

- `11_stock_basic_to_s3.py`
- `12_trade_cal_to_s3.py`
- `13_stock_st_to_s3.py`
- `14_stock_st_daily_fallback_to_s3.py`

这是“当天日更前置条件”，不要跳过。

### 2. `daily_incremental`

规则：

- 以本地 canonical `daily.csv` 的最后交易日为 `start_after`
- 读取 `trade_cal.csv`
- 找出 `(start_after, end_date]` 之间所有开放交易日
- 跳过已经存在于 `daily_incremental/` 的分区
- 只补缺的交易日

当前脚本会调用：

- `16_daily_incremental_to_s3.py --trade-date YYYYMMDD`

默认还会调用：

- `15_daily_basic_incremental_to_s3.py`

### 3. `daily_basic_incremental`

规则：

- 历史回补期间：继续按当前回补任务推进，不中断
- 回补完成后：每天按交易日追加 1 个 `trade_date=YYYYMMDD` 分区
- `market_cap / total_mv / circ_mv / turnover_rate / pe / pb / ps` 全部以这一层为正式来源

注意：

- 这层是估值/市值/换手正式层
- 不要再把这些字段塞回 `daily.csv`

### 4. canonical `daily.csv` merge

用本仓库脚本：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/merge_daily_incremental_into_daily.py \
  --operator codex \
  --base-csv ~/.qlib/raw_tushare/行情数据/daily.csv \
  --replace-base \
  --end-date YYYYMMDD
```

如果要顺手回传 `S3`：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/merge_daily_incremental_into_daily.py \
  --operator codex \
  --base-csv ~/.qlib/raw_tushare/行情数据/daily.csv \
  --replace-base \
  --end-date YYYYMMDD \
  --upload
```

### 5. 本地同步

本地原始缓存入口：

```bash
python3 scripts/sync_tushare_raw_from_s3.py inspect
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/sync_tushare_raw_from_s3.py --operator codex sync-daily
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/sync_tushare_raw_from_s3.py --operator codex sync-daily-basic-range --start YYYYMMDD --end YYYYMMDD
```

### 6. shared clean layer 刷新与 daily_basic 增强

日更入口推荐直接加：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/run_tushare_daily_update_via_ssm.py \
  --operator codex \
  --end-date YYYYMMDD \
  --refresh-clean-layer
```

这个开关会在远端刷新和本地 `daily.csv` merge 后调用：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/refresh_clean_daily_after_tushare_update.py --operator codex --end-date YYYYMMDD
```

该脚本负责：

1. 如果本地 `daily_basic_incremental` 落后，则同步缺失的 `daily_basic` 分区。
2. 如果 raw `daily.csv` 比 `daily_clean.parquet` 更新，默认只增量拼接新增交易日；只有 clean layer 缺失、schema/policy 变化、或显式 `--force/--update-mode rebuild` 时才全量重建。
3. 如果 `daily_basic` 比 clean layer 中的 enrichment 更新，或 clean layer 缺少增强字段，则调用：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/build_daily_clean_enhanced.py --operator codex --replace
```

最终 `data/clean/daily_clean.parquet` 应包含：

- `daily_basic_close`
- `turnover_rate / turnover_rate_f / volume_ratio`
- `pe / pe_ttm / pb / ps / ps_ttm`
- `total_share / float_share / free_share`
- `total_mv / circ_mv`
- `free_float_mcap`
- `ln_mcap_free / ln_total_mv / ln_circ_mv`

其中：

```text
free_float_mcap = daily_basic_close * free_share
```

单位为万元，与 `total_mv / circ_mv` 保持一致。

## 失败规则

### 当天 `daily` 返回空结果

如果：

```text
daily(trade_date=YYYYMMDD) 返回空结果
```

处理规则：

1. 视为“当日数据源未 ready”
2. 不回滚前面已经成功的基础表和增量分区
3. 记录 warning
4. 次日重试

### 某个基础表失败

处理规则：

1. 立即停止当天链路
2. 不继续跑 merge
3. 修复后重跑整条日更

### `daily_incremental` 中间某天失败

处理规则：

1. 保留已经成功的分区
2. 定位失败交易日
3. 单独补该日期
4. 补完再做 canonical merge

## Step3 数据契约对应关系

当前 Step3 已按下面口径处理：

- `daily.csv`：行情层
- `daily_basic_incremental`：估值/市值/换手层
- `market_cap / turnover_rate / PE / PB / PS`：优先从 shared clean layer 的 daily_basic 增强字段读取
- 不再默认拿 `amount` 代理 `market_cap / turnover_rate`

## 当前已验证事实

- `daily_incremental` 已成功补到 `2026-04-14`
- `2026-04-15` 在 Tushare 侧仍返回空结果
- 本地 canonical `daily.csv` 已经合并到 `2026-04-14`

## 下一步收尾

1. 等 `daily_basic_incremental` 历史回补完成
2. 如有需要，把 canonical `daily.csv` 的 merge/upload 迁到 EC2 执行，避免本机长时间上传
3. 监控 `refresh_clean_daily_after_tushare_update.py` 输出，确保 `daily_clean.parquet` 与 raw daily/daily_basic 同步
