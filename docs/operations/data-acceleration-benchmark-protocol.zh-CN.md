# Data Acceleration Benchmark Protocol

更新日期：2026-06-15

本文档定义 DuckDB / ClickHouse / ArcticDB / pandas parquet 的可比 benchmark 口径。所有测试必须遵守 `docs/operations/data-acceleration-roadmap.zh-CN.md` 的隔离边界。

## 隔离边界

benchmark 只允许写入：

- `/tmp/factorforge-data-acceleration-*`
- `factorforge/data/benchmarks/data_acceleration/`
- `factorforge/data/proofs/data_acceleration/`

benchmark 禁止写入：

- `factorforge/objects/`
- `factorforge/runs/`
- `factorforge/evaluations/`
- `factorforge/archive/`
- clean data output
- search worker output
- official factor library

## 第一批 DuckDB Smoke

命令：

```bash
UV_CACHE_DIR=/tmp/uv-cache-factor-data-api \
uv run --no-project --with pandas --with pyarrow --with duckdb \
  python scripts/benchmark_duckdb_data_api.py
```

默认读取 repo-local catalog：

```text
factorforge/data/catalog/data_catalog.json
```

脚本会复制一份临时 catalog 到 `/tmp/factorforge-data-acceleration-duckdb/`，只在临时 catalog 中给测试 dataset 注入：

```json
{
  "metadata": {
    "acceleration": {
      "default_backend": "duckdb"
    }
  }
}
```

主 catalog 和 canonical datamart 不会被修改。

## DuckDB Smoke Workload

默认代表日期：

- `20160104`
- `20200102`
- `20210930`
- `20240110`
- `20250711`

默认 dataset：

- `tradability_risk_flags_daily`
- `microcap_universe`
- `standard_full_market_universe`

每个 dataset/date 执行：

1. pandas/local_file reference read。
2. DuckDB accelerated read。
3. 比较 status、row_count、date_count、ticker_count、duplicate_key_count。
4. 记录 read seconds。

额外 join workload：

```text
microcap_universe
  JOIN tradability_risk_flags_daily
  ON trade_date + ts_code
```

检查：

- join row count 与 pandas reference 一致。
- `is_investable_core` 与 `is_investable_500m` 字段存在。
- 不写 Factor Forge research artifacts。

## Proof Schema

输出路径默认：

```text
factorforge/data/proofs/data_acceleration/duckdb_backend_smoke__YYYYMMDD.json
```

核心字段：

```json
{
  "verdict": "ACCEPT|BLOCK",
  "backend": "duckdb",
  "repo_sha": "...",
  "catalog_path": "...",
  "temporary_catalog_path": "...",
  "isolation": {
    "writes_factorforge_objects": false,
    "writes_factorforge_runs": false,
    "writes_factorforge_evaluations": false,
    "modifies_canonical_datamart": false
  },
  "read_results": [],
  "join_results": [],
  "issues": []
}
```

## ACCEPT 条件

- 所有已执行 read workload 的 DuckDB result 为 `ready` 或 `proxy_ready`。
- DuckDB 与 reference 的 row/date/ticker/duplicate counts 一致。
- join workload 与 reference row count 一致。
- proof 写入隔离路径。
- 未修改主 catalog。
- 未写 research artifacts。

## BLOCK 条件

- DuckDB backend 无法 import。
- 临时 catalog 读取失败。
- 任一代表日期结果与 reference 行数不一致。
- duplicate key count 不一致。
- join 结果行数不一致。
- 输出路径不在允许路径内。
