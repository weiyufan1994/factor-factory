# 日频数据预处理统一入口

这份说明只回答一个问题：

> Bernard、Humphrey、Codex、rdagent 以后怎么用同一条命令拿到一致的日频输入，而不是每个 agent 各自做一套清洗。

## 结论

以后日频输入分两步：

1. 先构建共享清洗层：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/build_clean_daily_layer.py --operator codex --start YYYYMMDD --end YYYYMMDD
```

2. 再把 `daily_basic` 增强字段合入共享清洗层：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/build_daily_clean_enhanced.py --operator codex --replace
```

或者在日更完成后使用自动收尾入口：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/refresh_clean_daily_after_tushare_update.py --operator codex --end-date YYYYMMDD
```

3. 再按 report 切片：

```bash
python3 scripts/preprocess_daily_data.py --report-id <report_id> --start YYYYMMDD --end YYYYMMDD
```

如果后面要接 qlib native provider，就直接加：

```bash
python3 scripts/preprocess_daily_data.py \
  --report-id <report_id> \
  --start YYYYMMDD \
  --end YYYYMMDD \
  --build-provider
```

## 这个入口负责什么

`scripts/build_clean_daily_layer.py` 负责：

1. 从本地可用 raw 层读取日频数据。
2. 调用共享 `get_clean_daily(...)` 执行制度化清洗。
3. 物化共享 clean layer：
   - `data/clean/daily_clean.parquet`
   - `data/clean/daily_clean.meta.json`

`scripts/build_daily_clean_enhanced.py` 负责：

1. 从本地 `daily_basic_incremental` 读取估值/市值/换手字段。
2. 计算：
   - `free_float_mcap = daily_basic_close * free_share`
   - `ln_mcap_free`
   - `ln_total_mv`
   - `ln_circ_mv`
3. 把 daily_basic 增强字段 merge 回 `data/clean/daily_clean.parquet`。

`scripts/refresh_clean_daily_after_tushare_update.py` 是日更收尾入口，负责：

1. 按需同步缺失的本地 `daily_basic_incremental` 分区。
2. 如果 raw `daily.csv` 已更新，默认增量拼接新增交易日；只有首次建库、字段结构升级、policy 变化或显式 force/rebuild 时才重建全量 `daily_clean.parquet`。
3. 如果 daily_basic enrichment 落后，则重新 merge daily_basic 增强字段。

`scripts/preprocess_daily_data.py` 负责：

1. 读取共享 clean layer。
2. 按 report/window/symbols 切出一份轻量 slice。
3. 物化 `daily_input__{report_id}.csv`。
4. 写出同名 metadata JSON，记录：
   - 数据来源
   - clean layer 路径
   - 过滤策略（继承自 clean layer）
   - 输出行数 / 股票数 / 日期数
5. 如果指定 `--build-provider`，再从这份 report slice 构建 qlib provider。

## 默认清洗策略

默认就是仓库里已经制度化的共享 policy：

- 前复权
- 去 `BJ`
- 去 `ST`
- 去上市不足 `60` 个交易日
- 去停牌
- 去涨跌停封板
- 去超过制度涨跌停上限的异常 `pct_chg`

这些过滤都按 `row trade_date` 做，不依赖未来行：

- `ST`：只判断当前行日期是否落在 ST 区间内
- 停牌：只看当日 `vol / amount / close`
- 上市不足：只看 `list_date` 到当前交易日的交易日数
- 涨跌停 / 异常 `pct_chg`：只看同一行的 `pct_chg / high / low / close`

价格复权也会统一调整：

- `open`
- `high`
- `low`
- `close`
- `pre_close`

如果确实要放宽，可以显式加参数到 `build_clean_daily_layer.py`：

- `--keep-bj`
- `--keep-st`
- `--keep-suspended`
- `--keep-limit-events`
- `--keep-abnormal-pct-move`
- `--adjust-mode none|forward|backward`

默认不建议改。

## 输出位置

共享 clean layer 默认输出：

- `data/clean/daily_clean.parquet`
- `data/clean/daily_clean.meta.json`

`daily_clean.parquet` 应包含行情清洗字段和 daily_basic 增强字段：

- `open / high / low / close / pre_close / pct_chg / vol / amount`
- `daily_basic_close`
- `turnover_rate / turnover_rate_f / volume_ratio`
- `pe / pe_ttm / pb / ps / ps_ttm`
- `total_share / float_share / free_share`
- `total_mv / circ_mv`
- `free_float_mcap / ln_mcap_free / ln_total_mv / ln_circ_mv`

如果给了 `--report-id`，`preprocess_daily_data.py` 的标准输出是：

- `runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.csv`
- `runs/<report_id>/step3a_local_inputs/daily_input_meta__<report_id>.json`
- `runs/<report_id>/qlib_provider/`（仅在 `--build-provider` 时生成）

补充说明：

- 如果设置了 `FACTORFORGE_ROOT`，这些相对输出默认会写到 `FACTORFORGE_ROOT/runs/...`
- 如果没有设置，但机器上存在 `/home/ubuntu/.openclaw/workspace/factorforge`，脚本会优先写到那个 workspace 输出根
- 如果没有设置，才会回落到仓库内的 `runs/`
- 在 EC2 skill wrapper 场景下，推荐始终通过 `FACTORFORGE_ROOT=/home/ubuntu/.openclaw/workspace/factorforge` 运行，这样输出会落到 workspace 可写目录，而不是 repo 目录

EC2 原始数据缓存也建议固定到专门目录：

- 默认优先：`/home/ubuntu/.openclaw/workspace/factorforge/data/raw_tushare`
- 非 root 环境才允许回退到 `~/.qlib/raw_tushare`
- root/SSM/EC2 自动化环境如果没有显式 `FACTORFORGE_LOCAL_DATA_ROOT` 且 persistent root 不存在，必须 fail closed，避免误写 `/root/.qlib`
- 这样数据可以长期保留在 EC2，下次不需要重新同步，只有你明确要求更新时再同步

如果不给 `--report-id`，就必须显式传 `--output-csv`，metadata 会默认写到同目录的 `*.meta.json`。

## 推荐用法

### 1. 先构建共享清洗层

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/build_clean_daily_layer.py \
  --operator codex \
  --start 20100104 \
  --end current
```

### 2. 合入 daily_basic 增强字段

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/build_daily_clean_enhanced.py --operator codex --replace
```

日更任务里更推荐使用：

```bash
FACTORFORGE_DATA_MUTATION_APPROVED=codex-approved python3 scripts/refresh_clean_daily_after_tushare_update.py --operator codex --end-date YYYYMMDD
```

### 3. Step3A 标准日频输入

```bash
python3 scripts/preprocess_daily_data.py \
  --report-id DONGWU_TECH_ANALYSIS_20200619_02 \
  --start 20100104 \
  --end current
```

### 4. native qlib 前的一次性准备

```bash
python3 scripts/preprocess_daily_data.py \
  --report-id DONGWU_TECH_ANALYSIS_20200619_02 \
  --start 20100104 \
  --end current \
  --build-provider
```

### 5. 只对某个股票池做研究

```bash
python3 scripts/preprocess_daily_data.py \
  --report-id MY_SUBUNIVERSE_TEST \
  --start 20240101 \
  --end 20240331 \
  --symbols 000001.SZ,000002.SZ,600000.SH
```

### 6. 用股票列表文件

```bash
python3 scripts/preprocess_daily_data.py \
  --output-csv /tmp/my_daily.csv \
  --start 20240101 \
  --end 20240331 \
  --symbols-file /tmp/universe.txt
```

## 制度化要求

以后约定：

1. 清洗重活优先通过 `build_clean_daily_layer.py` 完成，不要在 Step3A 重复全量清洗。
2. `daily_basic` 增强字段优先通过 `build_daily_clean_enhanced.py` 或 `refresh_clean_daily_after_tushare_update.py` 合入 shared clean layer，不要在因子脚本里重复拼 daily_basic。
3. Step3A 的日频 snapshot 优先通过 `preprocess_daily_data.py` 从共享 clean layer 切片生成。
4. Step4 不要再各自读取原始 `daily.csv` 做临时清洗。
5. qlib provider 必须从这份 report slice 构建，而不是从别的来源临时拼。
6. 如果 policy 要改，就改共享数据层和这份文档，不要在 agent 脚本里偷偷改。

## 为什么要这样做

因为我们之前已经踩过这些坑：

- 未复权价格跳点污染收益
- `BJ / ST / 新股 / 停牌 / 涨跌停` 没清干净
- provider 和 Step4 读的不是同一份数据
- 不同 agent 各自处理一遍，结果口径漂移

这个统一入口的目的，就是把这些差异收口成一条显式流程。
