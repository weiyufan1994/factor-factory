# PF/VV 研究进度与代码效率复核

复核日期：2026-09-21。用户所称 PVFF 在当前项目中对应民生证券 PF/VV 原文基线。本次核查该基线，独立的 EVENT_U、Signed-A、IPPS/IPSI 扩展不合并评价。

结论：实现有明确的数学边界、分层和内存控制，也有较完整的局部验证；当前速度仍有明确的优化空间。现有真实日志及本次合成剖析支持优先消除时间字符串处理和重复数据访问，再优化滚动状态与账户内核。

本次没有修改研究代码、重跑真实行情或读取 OOS。以下真实研究状态取自现存本地运行证据，记录完成时间为 2026-09-08 22:51 UTC；不代表进行了新的云端状态查询。

## 研究状态

原文基线的 Ultimate 本地 IS 运行记录为 PASS，Step6 决策为 `iterate`。研究窗口为 2016-01-04 至 2025-07-11，2,313 个交易日。组合因子文件为 9,125,946 行；其中包含缺失值及额外诊断键，不能全部视作有效可交易信号。

| 组合指标 | 已有 Step4 结果 |
| --- | ---: |
| 月度 Rank IC 均值 | 10.6655% |
| 成熟月度 IC 观察数 | 113 |
| 多头净年化 | 4.4426% |
| 同规则零费用账户年化 | 11.1887% |
| 净 Sharpe | 0.3368 |
| 净最大回撤 | -34.0636% |

结论是保留排序信息、继续检验增量解释和交易实现。`formal_proof_eligible=false`，未允许 OOS 或正式 promotion。高 IC 与较弱的净风险收益同时存在，不能用代码测试通过替代投资结论。

原研究说明：[PF/VV 原文基线本地 IS 报告](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/factor_research/mszq_pfvv_source_baseline/mszq_pfvv_source_first_is_20260908/reports/PFVV原文基线本地IS研究报告.zh-CN.md)。

## 已有真实耗时

| 阶段 | 输入或工作量 | 实际记录 |
| --- | --- | --- |
| 研究机分钟预处理 | 2,234,784,195 行原始分钟数据；2,313 日；约 31.67 GB 压缩源数据 | 5:51:31；CPU 97%；峰值 RSS 2.063 GiB；swap 0；退出码 0 |
| 本地 Step4 评估后端 | 复用正式因子值；组合/PF/VV 各 10 组与基准、各含费/零费账户 | 2,576.081 秒，约 42.93 分钟 |

预处理产出 9,109,745 行日状态。派发收据中五个源码/重建配置哈希与当前文件一致。预处理按日串行执行，派发环境将 BLAS/OpenMP 线程设为 1；该次 CPU 记录接近占满一个核心。

评估包含输入归一化、SQLite 查找库建立、66 次账户模拟及输出，不是只计算一条 NAV。该次已经复用 Step4 因子值，不能把 42.93 分钟归入分钟因子计算。评估 payload 中约 1.92 GB 后端峰值是预估值；本次没有找到该后端实际峰值 RSS 或细分阶段计时。

## 做得较好的部分

- 数值核、日测量、20 日状态投影、交易账户与评估封装分别实现，原文约定集中记录；纯数值核不访问网络。
- 原始分钟数据按日处理；完整截面在单日内保留，20 日滚动状态有限，后续研究消费准备好的日状态。
- 评估按 65,536 行读取 Parquet，常驻月末因子与有限日期缓存，账户结果逐个落盘后释放。组合、PF、VV 共用本次建立的查找库。
- 缺失值、完整交易日历、证券边界、开盘域、并列峰、交易限制、含费与独立零费用账户均有对应测试。

## 主要性能发现

### P2：分钟准备反复进行全表时间字符串与身份处理

[日测量入口](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py:49)与[VWAP 入口](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py:103)分别解析日期、匹配证券代码，并将整日时间转换为 `HH:MM:SS` 字符串。

本次 2,000 只证券 × 240 分钟的合成准备剖析：共 3.427 秒，其中 `strftime` 累计 1.549 秒，约 45%；字符串正则匹配累计约 0.777 秒。后者与其父级函数计时有重叠，不能把全部累计时间相加。VV 数值核在该次剖析中累计约 0.368 秒。

建议用验证后的 datetime/整数时隙做筛选，复用同一天的日期、代码与网格验证结果，减少拷贝。保留原有精确分钟、重复键和价格有效性检查。这个样本说明数据准备值得先优化，不能据此承诺完整研究提速倍数。

### P2：没有订单的持仓日仍读取成交窗口价格

[账户循环第 469 行](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_step4_portfolio_evaluator_candidate_v1.py:469)在判断是否到退出日之前，读取约束、VWAP 与日价格。普通持仓日不消费该 VWAP，但依然触发其日期分区读取。

本次用同一个真实账户函数与 SQLite 适配器构造 2 只证券、8 日、仅首末日交易的合成样本，连续计算含费和零费账户。每张表发生 16 次 SQL 查询；其中成交价格表有 12 次查询发生在无订单日。建议把 VWAP 读取移至确需执行的分支，保留每日退市检查和估值。

### P2：账户之间共享查找对象，但没有共享同日读取过程

[账户入口](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_monthly_evaluation_v1.py:342)先完整模拟净账户，再完整模拟零费用账户；各组和分量也逐个完整遍历日历。[SQLite 缓存](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_daily_lookup_store_v1.py:96)只保留 4 日，后一个账户回到窗口起点时会重新查询历史日期。

这是一种有效的内存约束设计，但还可以在同一交易日向多个独立账户共享价格与约束数组。现金、持仓和费用路径仍须独立计算，不能把零费用收益近似成净收益加回费用。另可对输入身份完全相同的研究重复运行建立持久查找缓存；当前后端每次创建新临时库，成功后清除。

### P2：20 日状态更新含大量逐证券小对象操作

[状态更新函数](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_partitioned_v1.py:165)每日逐证券复制两组 deque，执行两次 pandas 标量查询，再转数组计算标准差。

本次 60 日 × 2,000 只证券的合成日状态剖析共 3.657 秒，状态更新累计 3.021 秒，约 83%；包含 164,000 次标准差调用与 240,000 次 Series 查询。建议改为按固定证券映射组织的数组环形缓冲，并批量计算；必须保持完整日历、缺失值传播、样本标准差与新增证券热身语义。以上耗时含 profiler 开销，不包括 Parquet I/O。

### 恢复与并行仍有改进空间

[预处理生产器](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py:136)按日串行，失败后保留 partial，但入口要求新的输出目录，没有验证既有日文件后续跑的分支。长任务后段失败会增加重新处理成本。

可先加入基于输入、代码和日输出哈希的断点续跑，再根据内存预算并行处理独立交易日。PF 需要完整同分钟截面，不能随意按股票拆分该截面；20 日时序投影必须继续按交易日顺序消费。

## Rust/C++ 的适用位置

优先级建议：时间与代码归一化复用 → 消除不必要查询并共享同日输入 → 数组化 20 日状态 → 对剩余热点评估 Rust/C++。

适合原生内核的候选是 VV 递归切分、滚动状态、账户持仓循环。仅改写 PF/VV 数值函数不会自动消除准备和评估层的重复工作。迁移需保持原因子定义、交易时序、现金路径和所有缺失/受阻成交语义，并做同输入的一致性核对。

## 本次验证范围

12 个现有 PF/VV 测试文件：首次 107 项通过、3 项因未声明引擎路径而跳过；指定项目自带真实引擎后，单独补跑该 3 项均通过。合计 110 个不同测试通过，无剩余跳过。包内引擎与原运行所声明路径下的当前引擎文件 SHA256 相同。

另做了合成单日准备、60 日状态及 SQLite 查询计数抽查。没有进行全面投资正确性审计、原 PDF 重新裁定或全窗口性能重跑；历史收益仍来自原运行。

[结构化证据、源码哈希与剖析结果](/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907/docs/operations/pfvv-code-performance-review-20260921.json)。
