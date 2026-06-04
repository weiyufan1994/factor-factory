# Factor Forge Qlib Daily Provider 发布说明

## 目标

把已经清洗好的日频数据发布成 Microsoft Qlib 可读取的 provider/store，用于 Step4 的 qlib native 回测底座。

这不是新的数据清洗链路，也不是因子值计算链路。

## 边界

Factor Forge 仍按原架构分工：

- Data API / 清洗链路负责提供 `clean_daily_bar`。
- Step3/Step4 的 direct code / operator / hybrid 负责计算因子值。
- Qlib provider 只保存日频市场数据、交易日历和 instrument 元信息，供 qlib backtest 读取。
- Step5/Step6 只消费 Step4 的正式 factor values 和 evaluation payload，不直接读 raw source data。

禁止把以下逻辑塞进 Qlib provider publisher：

- 拉取或修复 Tushare 原始数据；
- 剔除停牌、一字涨跌停等清洗逻辑；
- 计算因子值；
- 猜测 report_id、Step3A local path 或 runtime root；
- 绕过 Data API catalog 去扫描 raw S3/local path。

## 推荐部署形态

研究机持有完整数据和 provider：

```bash
export QLIB_PROVIDER_URI=/home/ubuntu/.qlib/qlib_data/cn_data
```

Mac 本地有两种用法：

1. 需要轻量验证时，从 S3 同步 provider 到本地后设置：

```bash
export QLIB_PROVIDER_URI=/Users/humphrey/.qlib/qlib_data/cn_data
```

2. 需要重计算或正式研究时，把 Step3B/Step4 任务派发到研究机执行。

## 从 Data API 发布

```bash
python3 scripts/publish_qlib_daily_provider.py \
  --data-api \
  --catalog-path /path/to/data_catalog.json \
  --dataset-id clean_daily_bar \
  --start-date 20100101 \
  --end-date 20260601 \
  --provider-dir /home/ubuntu/.qlib/qlib_data/cn_data \
  --instrument-style legacy_qlib \
  --raw-smoke \
  --qlib-smoke \
  --write-env-file /home/ubuntu/.factorforge/qlib_provider.env
```

如果需要同步到 S3：

```bash
python3 scripts/publish_qlib_daily_provider.py \
  --data-api \
  --catalog-path /path/to/data_catalog.json \
  --start-date 20100101 \
  --end-date 20260601 \
  --provider-dir /home/ubuntu/.qlib/qlib_data/cn_data \
  --sync-s3-uri s3://<bucket>/<prefix>/qlib_data/cn_data/
```

## 从已有 clean daily 文件发布

用于受控验收或研究 run 局部切片：

```bash
python3 scripts/publish_qlib_daily_provider.py \
  --input /path/to/clean_daily_bar.parquet \
  --provider-dir /home/ubuntu/.qlib/qlib_data/cn_data \
  --instrument-style legacy_qlib \
  --raw-smoke
```

## 输出

provider 目录结构：

```text
cn_data/
  calendars/day.txt
  instruments/all.txt
  features/<instrument>/<field>.day.bin
  provider_metadata.json
  publish_report.json
```

`provider_metadata.json` 和 `publish_report.json` 记录：

- source 类型和路径/catalog；
- instrument 风格；
- row/date/instrument/feature file 计数；
- calendar 起止；
- raw format smoke 结果；
- 可选的 Microsoft Qlib read smoke 结果；
- 可选 S3 sync 结果。

## Step4 使用方式

Step4 qlib native backend 优先读取 backend/env 中的 `QLIB_PROVIDER_URI`。

如果没有设置 `QLIB_PROVIDER_URI`，才回退到：

```text
/home/ubuntu/.qlib/qlib_data/cn_data
~/.qlib/qlib_data/cn_data
runs/<report_id>/qlib_provider
```

`scripts/run_qlib_native_report.py` 会读取 `provider_metadata.json` 的 `instrument_style`，把 factor signal 的 instrument 风格与 provider 对齐。

## 验收标准

最小验收：

```bash
python3 -m py_compile scripts/build_report_qlib_provider.py scripts/publish_qlib_daily_provider.py scripts/run_qlib_native_report.py
python3 scripts/publish_qlib_daily_provider.py --input <clean_daily.parquet> --provider-dir /tmp/ff_qlib_provider --raw-smoke
```

研究机正式验收：

```bash
python3 scripts/publish_qlib_daily_provider.py \
  --input <clean_daily.parquet or Data API catalog> \
  --provider-dir /home/ubuntu/.qlib/qlib_data/cn_data \
  --raw-smoke \
  --qlib-smoke
```

如果 `import qlib` 导入的是非 Microsoft Qlib 包，`--qlib-smoke` 必须失败或显式 `SKIPPED`，不能把错误包当成成功。
