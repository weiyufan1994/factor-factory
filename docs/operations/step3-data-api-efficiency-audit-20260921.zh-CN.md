# Step3、分钟 Data API 与 PF/VV 效率核查

核查日期：2026-09-21。范围是当前本地工作树、Step3 实际调用代码、线上 active catalog 元数据、PF/VV 已有运行记录及离线合成验证。两个代码仓库均有既有未提交修改；结论对应当前文件内容，不代表远端部署版本。本次没有修改业务代码、替换目录、重新运行真实行情或访问 OOS 行情。

## 结论

1. 分钟 API 和 Step3 标准取数入口已存在，基本调用链可用。问题主要在统一数据发现、分钟标准化交付以及大规模取数方式，不能概括为“没有分钟 API”。
2. PF/VV 的分钟准备程序直接读取原始 S3 分区，未使用独立 SDK。其共性数据处理仍落在研究项目中，说明平台能力与实际消费者之间尚有缺口。现有证据不能把其 5 小时 51 分钟全部归因于 Data API 读取慢。
3. 当前只有部分向量化、列选择、分区读取和缓存能力，未做到完整链路的高效并行。先修取数路径与重复工作，再决定剩余热点是否需要 Rust/C++。

## 1. 编码 agent 能否简单取数

[SDK 的 get_minute_bars](/Users/humphrey/projects/factorforge-data-api/factorforge_data_api/client.py:89)支持日期、证券列表和字段；返回数据表、来源、字段映射及基本覆盖统计。本次成功导入 Factor Forge 桥接层，确认实际加载的是 `/Users/humphrey/projects/factorforge-data-api/factorforge_data_api`。

[Step3A](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/skills/factor-forge-step3/scripts/run_step3.py:1923)通过桥接层获取小样本；[Step3B](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/skills/factor-forge-step3/scripts/run_step3b.py:974)向 `compute_factor` 注入 `daily_df` / `minute_df`，并处理字段别名及可选 Polars 转换。因此普通编码 agent 已有入口，不应自行猜 S3 路径。

但这个接口当前主要交付原始分钟行。通用读取入口没有同时承诺完整交易日历、指定分钟网格、停牌/ST/PIT 股票池或统一研究窗口准备完成。已有质量摘要和日聚合模块，也不等于这些能力已自动进入 `get_minute_bars`。

### 数据目录与缓存配置不一致

本次只读获取线上 `s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json`，与本机实际默认目录比较：

| 项目 | 本机默认目录 | 本次线上快照 |
| --- | --- | --- |
| 数据集条目数 | 11 | 34 |
| minute_bar 版本 | raw_v1 | raw_v1 |
| minute_bar 分区缓存开关 | true | 未设置，当前 SDK 判定 false |
| prepared_minute_bar 条目 | 无 | 无 |
| daily_minute_features 条目 | 无 | 无 |

本机默认目录位置为 `/Users/humphrey/projects/factorforge/data/catalog/data_catalog.json`。线上有 29 个名称未出现在此本机目录，本机也有 6 个名称未出现在本次线上快照；不能直接把一个目录覆盖到另一个上而忽略用途和来源。

这证明不同入口的数据发现与读取策略不一致。按当前 SDK 使用线上快照时，分钟读取会进入无 SDK 分区缓存的路径；不代表所有运行中的 worker 都采用这份目录，也不代表相应数据在其他位置不存在。目录中的覆盖日期不是本次对原始存储完整性的重新验证。

证据：本机目录 SHA256 `9fab300591ebe5454d7bdb1beece17f4d4b7d30f0b50a733635402fb46274b5a`；线上快照 SHA256 `98b883004d5ecef38c77431b5986cb2fa07851b706c81c2fc6d5ef8ef4cbd018`。

### 小样本读取未充分提前过滤

[本地日期分区读取](/Users/humphrey/projects/factorforge-data-api/factorforge_data_api/backends/local_file.py:27)先将分区所选列转成 pandas，再由 [client](/Users/humphrey/projects/factorforge-data-api/factorforge_data_api/client.py:162)过滤股票。[S3 无缓存日期分区分支](/Users/humphrey/projects/factorforge-data-api/factorforge_data_api/backends/s3_file.py:64)使用同样没有传入股票过滤条件的辅助函数。缓存合并读取分支则已有 Arrow 过滤，不能把问题泛化到所有分支。

本次合成 2,000 只证券 × 240 分钟，调用真实公开接口只请求 2 只证券：底层先产生 **480,000 行**，最终返回 **480 行**。这是读取后物化行数的 1,000 倍放大，不代表网络字节或耗时也一定放大 1,000 倍。字段投影有效，`volume -> vol` 别名有效。

### 完整性报告还不足以让 agent 直接放心使用

`_coverage()` 当前将 `missing_dates` 固定为 `[]`。合成查询请求 2016-01-04 至 2016-01-05，但故意只提供第一日，返回仍为 `ready`，缺失日期报告仍为空。基本非空/重复键检测通过，不等于查询窗口完整。

需要用明确的交易日历和分钟域报告缺失；原始读取接口不能擅自补零、填价或改变开盘边界。时间类型、单位、重复键、网格、股票池与缺失策略应成为可复用且显式的交付契约。

## 2. PF/VV 是否被 Data API 拖慢

PF/VV 实际 `data_prep_master` 使用 `input_mode=derived_state_with_daily`，注入研究机准备的日状态目录；原始分钟路径为空，`data_api_resolution` 和 `step4_data_contract` 在该准备对象中为空。Step3B 使用受限日状态样本，不负责再读取全历史分钟数据。

[上游日状态生产器](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py:136)自行拼装已限定的原始分区路径，调用 boto3 下载，解析 Parquet，执行日测量和成交窗口计算。它没有调用独立 SDK，也不会自动享受 SDK 的分区缓存或预热。

平台缺口在于：研究代码承担了原始读取、时间及证券标识归一化、分钟域检查等可复用任务。PF 截面条件、VV 递归切分和特定成交窗口的数学定义仍属于研究逻辑，应通过明确参数/契约消费公共底座。

既有 2026-09-08 运行记录：2,313 个交易日、约 22.35 亿行原始数据，准备耗时 21,091 秒（5:51:31），CPU 97%，峰值 RSS 2.063 GiB。结合源码的按日串行循环，证据支持该次执行接近占满一个核心；不能由此断言新 API 能提速某个倍数。

此前同一工作区的合成剖析已经发现反复格式化时间字符串、重复正则检查等热点，详见 [PF/VV 性能复核](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/docs/operations/pfvv-code-performance-review-20260921.zh-CN.md)。改进 SDK 后必须实际接入生产器，才能改善这条链路。

## 3. 当前效率与并行状态

| 环节 | 已具备 | 当前缺口 |
| --- | --- | --- |
| SDK 分钟读取 | 日期分区、列选择；部分分支提前过滤；可选本地缓存 | 日期分区逐个处理；公开返回值是完整 pandas 表，未提供有内存上限的按日流式迭代入口 |
| SDK 缓存下载 | 重试、超时、临时文件替换 | 正常 fetch 的冷分区逐日下载；不同目录决定是否启用缓存 |
| 独立预热工具 | `prewarm_data_api_cache.py` 默认 24 个下载线程 | 是另行调用的工具，标准 Step3 取数和 PF/VV 生产器未自动调用它 |
| Arrow / NumPy | 原生计算，Arrow 可使用内部线程 | 底层线程不等于跨日期或跨账户并行 |
| PF/VV 日测量 | 单日有界内存、NumPy 数值部分 | 按日串行；失败保留 partial，但要求新目录，未验证续跑 |
| PF/VV 滚动状态 | 20 日有限状态 | 逐证券小对象、标量访问和重复标准差调用 |
| PF/VV 回测 | 限制内存的 SQLite 日期缓存 | 66 个账户路径串行遍历历史，重复读取同日输入，存在无订单日读取成交价的开销 |
| 通用 self_quant quick 分支 | 长表计算、共享评估上下文 | 当前资源及性能输出均声明 `parallelism=1` |

这里的结论针对审阅到的计算路径；研究组织中并行调用多个研究 agent，不代表分钟处理和回测内核已经并行。

缓存及读取并发也不能直接通过增加线程解决：当前下载临时文件名依赖进程号，同进程重复请求相同分区需补锁或请求隔离；桥接层临时修改 Arrow S3 构造器的方式也需做并发安全审查。以上是源码风险识别，本轮未做竞争条件复现。

## 4. 建议改进顺序与验收

1. **统一发现与交付。** 固定每次研究使用的目录来源、版本及哈希；给 Step3 提供可运行的小样本入口，以及明确的字段类型、单位、分钟域和完整性报告。先消除本机/研究机/线上目录差异，不靠增加说明文字让 agent 自行拼接。
2. **优化独立 SDK。** 在转 pandas 前过滤证券及日期；已有标准日期避免逐行解析；提供按日批次、内存上限、受控预取和可复用缓存。冷缓存、热缓存与只取两只股票分别验收，记录读取行数和字节数。
3. **接入 PF/VV 消费者。** 公共数据归一化只做一次，保留原研究定义；按独立交易日有界并行，日内保留完整截面，再按交易日顺序执行滚动状态。加入按输入/代码/输出身份验证的续跑。
4. **优化回测复用。** 多个独立账户共享同日只读行情与约束，减少无效成交价读取；每个账户的持仓、现金和费用仍独立推进。随后再对剩余数值热点选择 Rust/C++。

验收应同时包括：相同输入的因子/交易/NAV/metrics 一致性、分钟缺失检测、峰值内存，以及指定数据规模上的冷/热读取和全流程耗时。不能用单元测试通过代替这些性能证据，也不能用加核改变研究时序或缺失语义。

## 本次验证

- 独立 SDK 的基础接口与分钟聚合测试：15 项通过。
- Factor Forge 的 Data API 桥接、Step3 窗口、准备样本派发与 Step4 数据契约测试：42 项通过。
- 合计 57 项既有测试通过；另完成公开分钟 API 的合成读取计数、字段别名和缺失日期报告验证。
- 本次没有做真实 S3 分钟冷/热性能测试，没有查询当前 worker 的部署/资源状态。线上检查仅下载目录元数据。

[结构化证据](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/docs/operations/step3-data-api-efficiency-audit-20260921.json)。
