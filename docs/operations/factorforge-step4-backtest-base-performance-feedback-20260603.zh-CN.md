# Factor Forge Step4 回测基础数据与性能架构反馈

Date: 2026-06-03

Audience: Factor Forge Architect / Reviewer

## 1. 结论

这次 Alpha038 Step4 性能排查说明，当前长期瓶颈不只是某个算子慢，也不只是 CSV 写得慢，而是 Step4 仍把“因子正式值生成”和“回测基础数据准备”混在同一轮执行里。每次因子 rerun、loop child、multibranch sibling 都可能重复准备 T+1 label、signal-return merge、quantile diagnostics 和 qlib diagnostics。

已修复的点：

- Step4 full factor CSV 不再作为默认正式输出；
- qlib diagnostics 可以复用 shared evaluation context，不再重复做大表 forward-return merge；
- wrapper / validator 路径已经能证明这些窄修生效。

但长期缺口仍在：

- backtest base data 没有独立、可复用、可审计的 dataset contract；
- Step4 reuse gate 仍可能因为 `universe_hash` 等身份字段不一致而重跑大表流程；
- shared evaluation context 每次 Step4 都重建；
- self_quant / qlib 仍各自扫描大表做 IC、quantile、NAV 或 diagnostics；
- performance profile 仍需要更清楚地区分 factor compute、backtest base preparation、evaluation backend。

因此建议把本问题定义为“Step4 回测基础数据架构缺口”，而不是单纯的 I/O 优化问题。

## 2. 用户关切

用户连续提出了三个问题：

1. Step4 是否一直在生产 CSV，如果耗时就不应生产，parquet 是否更合适？
2. Step4 是否一直在重复计算？
3. 回测基础数据是否应该预先准备好，而不是每个因子都重复计算、重复读写？

这三个问题指向同一件事：Factor Forge 需要把“因子值”与“回测基础数据”解耦。因子值每个因子不同，必须计算；但 forward return label、交易日历、tradable mask、ST / 停牌 / 涨跌停过滤、成本模型输入、行业 / 市值暴露等基础数据，在同一数据版本、窗口、universe 和 label policy 下应当可复用。

## 3. Alpha038 观察到的证据

本轮 Alpha038 路径中，曾观察到 Step4 写 full factor CSV：

- `factor_csv_bytes=355811594`

窄修后，Step4 改为以 parquet 为正式输出，仅保留 sample CSV：

- `factor_csv_bytes=0`
- `factor_csv_sample_bytes=395505`
- `factor_parquet_bytes=82105768`

qlib diagnostics 复用 shared evaluation context 后，重复 merge 明显下降：

- qlib `merge_forward_returns`: `56.10s -> 2.36s`
- qlib total: `93.51s -> 41.66s`

但 Step4 总体仍然偏慢：

- Step4 total 仍约 `330s`
- shared evaluation context build 约 `54.43s`
- self_quant total 约 `46.83s`
- qlib quantile diagnostics 约 `24.91s`
- reuse miss reason 仍出现 `universe_hash`

这说明 full CSV 和 qlib duplicate merge 是真实问题，但不是全部问题。剩余成本主要来自“每轮重新构建回测评估上下文”和“大表重复扫描”。

## 4. 推荐的长期架构

建议引入独立的 backtest base dataset，作为 Step4 的正式输入之一。

### 4.1 Backtest base dataset 内容

在同一 `data_version + window + universe + label_policy + tradable_policy + cost_policy` 下，预先生成并缓存：

- T+1 / T+k forward return label table；
- tradable universe mask；
- ST、新股、停牌、涨跌停等不可交易过滤；
- 成本模型输入；
- trading calendar；
- optional industry / market cap exposure；
- optional qlib provider local cache 或 report-scoped provider 索引。

这些内容不应在每个因子的 Step4 中重复构造。

### 4.2 Step4 只做因子相关工作

每个因子正式运行时，Step4 应只做：

1. 读取 `factor_values.parquet`；
2. 根据 `backtest_base_dataset_id` 读取预生成的回测基础数据；
3. join factor 与 label / tradable mask；
4. 计算 IC、rank IC、quantile NAV、long side、cost-adjusted metrics；
5. 写 evidence tables / plots / validation profile。

如果 backtest base dataset 已命中，Step4 不应再重新构建 label、calendar、tradable filter 或 qlib diagnostics base。

## 5. 必须新增或强化的合同

建议新增 `backtest_base_dataset_contract`，至少包含：

- `backtest_base_dataset_id`
- `source_data_version`
- `clean_data_hash`
- `window_start`
- `window_end`
- `universe_id`
- `universe_hash`
- `label_policy`
- `tradable_policy`
- `cost_policy`
- `calendar_hash`
- `artifact_paths`
- `artifact_hashes`
- `producer_step`
- `producer_repo_sha`
- `created_at`
- `validator_verdict`

Step4 profile / wrapper proof 应明确记录：

- `backtest_base_reuse_hit=true|false`
- `backtest_base_reuse_reason`
- `backtest_base_dataset_id`
- `backtest_base_load_seconds`
- `factor_values_load_seconds`
- `evaluation_seconds`
- `write_outputs_seconds`

## 6. 建议的 BLOCK token

为了避免坏缓存或身份不清的复用污染正式研究，建议加入硬 blocker：

- `BLOCK_BACKTEST_BASE_DATASET_MISSING`
- `BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH`
- `BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH`
- `BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH`
- `BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH`
- `BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN`
- `BLOCK_STEP4_REUSE_GATE_AMBIGUOUS`

其中 `BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN` 应用于正式生产路径：大规模 `factor_values` 不应默认写 full CSV。CSV 可以作为 sample / evidence / debug 输出，但不应作为正式主 artifact。

## 7. Data API 边界

Step3A / Step4 应是 Data API consumer，而不是 clean data owner。

推荐边界：

- clean data / canonical data 由 Data API 或上游数据层负责；
- Step3A 消费 Data API，准备 report-local factor input；
- backtest base producer 消费 Data API，生成可复用 label / tradable / cost dataset；
- Step4 消费 `factor_values.parquet + backtest_base_dataset`；
- Step4 不应修改 clean data，也不应临时发明 clean-data processing。

这可以保持 Mac、EC2、worker 的 source-of-truth 清晰，也能避免研究路径对 clean data 产生副作用。

## 8. Performance profile 应补强

当前 profile 已能显示部分阶段耗时，但建议进一步拆成四类：

1. factor I/O:
   - load factor values
   - normalize / align factor index
2. backtest base:
   - load base dataset
   - validate identity
   - label / mask / cost availability
3. evaluation:
   - IC
   - rank IC
   - quantile assignment
   - quantile NAV
   - long side
   - cost adjusted
4. output:
   - write parquet evidence
   - write small CSV sample
   - write plots
   - write profile / validator evidence

同时应保留 wrapper wall time。只看 adapter-internal time 容易低估真实耗时。

## 9. 对 multibranch / loop 的影响

如果不解决 backtest base 复用，后续 multibranch loop 会被线性放大：

- 一个 parent 后面 N 个 child sibling；
- 每个 sibling 都重复构建 label / merge / qlib diagnostics；
- loop 再进入下一轮后继续重复。

这会导致研究时间被基础数据准备吞噬，而不是花在真正的 factor revision 上。

正确状态应是：

- siblings 共享同一个 backtest base dataset；
- 每个 child 只新增自己的 `factor_values.parquet` 和 evaluation result；
- branch comparison 直接基于各 child evaluation summary 比较；
- selected child 继续下一轮 Council；
- non-selected siblings 只进入 sibling memory，不再触发 next-parent 路径。

## 10. 建议优先级

P0:

- 正式生产路径禁用 full factor CSV 默认输出；
- 只允许 small sample CSV / evidence table；
- wrapper proof 必须记录 full CSV disabled。

P1:

- 引入 `backtest_base_dataset_contract`；
- 预生成并缓存 forward return label、tradable mask、calendar、cost model inputs；
- Step4 必须通过 dataset id + hash 消费该 base。

P1:

- Step4 reuse gate 改为 first-class contract；
- reuse miss 必须输出清楚、可审计的 reason；
- `universe_hash` 等 identity 字段必须稳定。

P2:

- self_quant 与 qlib diagnostics 共享同一 evaluation context / base dataset；
- 不允许 qlib 再单独重复做同样的大表 merge。

P2:

- performance profile 顶层加入 acceptance summary；
- 明确显示 base reuse hit/miss、backend、wall time、phase breakdown。

P3:

- 探索 lazy parquet scan、column pruning、partitioned dataset、Polars backend；
- 但这些应排在 backtest base contract 之后，否则只是局部加速，不能解决重复计算的结构问题。

## 11. 验收标准

建议架构师修复后，用真实因子 production proof 验收，而不是只跑 smoke。

验收时至少回传：

- repo sha；
- report id / run id；
- artifact root；
- Step3B backend；
- Step4 backend；
- `backtest_base_dataset_id`；
- `backtest_base_reuse_hit`；
- Step4 phase breakdown；
- full factor CSV 是否禁用；
- factor parquet path / hash；
- validator verdict；
- wrapper proof status；
- no clean data processing；
- no search worker；
- no official promotion unless promotion gate truly passed。

推荐用一个 fresh report id 跑真实 Alpha101 因子，并额外跑一次 same report rerun，验证第二次 Step4 不再重复准备 backtest base。

## 12. 总结

这次问题的本质不是“Step4 写 CSV 太慢”这么窄，而是正式研究链路缺少“回测基础数据预生成与复用”的架构合同。

短期应确保：

- parquet 是正式主输出；
- full CSV 默认禁用；
- qlib / self_quant 不重复 merge。

长期应确保：

- backtest base dataset 成为 Step4 的正式输入；
- reuse identity 可验证；
- 每个因子只计算自身 factor values；
- Step4 不再重复构建所有因子共享的 label / mask / calendar / cost 数据。

这会直接决定 Factor Forge Ultimate 能否支撑真实生产级 loop、Council revision 和 multibranch research，而不是每次把时间消耗在同一套基础数据读写与重复计算上。
