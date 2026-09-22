# Factor Forge Step3–5 工程基线与工作顺序

日期：2026-09-20。

目标：让 Ultimate 的 Step3、Step4、Step5 快速、稳定地完成代码编制、回测和 metrics 生产，同时保持研究规格、数值语义、交易时序及证据来源准确。

本文是 IT 工程接手时的初步盘点与工作队列，不是完整代码审计、性能验收或因子研究结论。

## 1. 工程职责与验收对象

| 环节 | IT 负责的结果 | 验收重点 |
| --- | --- | --- |
| Step3A | 数据字段、可用时间、单位、日历、窗口与依赖的明确映射 | 缺失依赖提前暴露；字段和 PIT 语义可追溯；可复用数据有明确版本 |
| Step3B | 按已冻结规格生成 operator / direct_code / hybrid 实现 | 数学对象不变；参考实现一致性；NaN、并列值、预热与分块边界正确；样本执行证据完整 |
| Step4 | 正式因子值、交易/净值证据、各评估后端的 metrics 与诊断 | 收益标签合法；现金、持仓、交易约束和成本正确；计算有内存上限；缓存身份一致；失败可定位 |
| Step5 | 从同一份 Step4 证据生成评价、案例与归档 | 指标来源明确；不重复扣费；缺失值不伪装成零；失败状态不变成成功；归档与实际消费者读回一致 |
| 公共算子 | 可复用、可验证、有性能记录的实现 | 每个算子的数学定义、输入输出、窗口、缺失/并列值策略、复杂度和适用限制明确 |

工程成功与因子收益好坏分别记录。修复或加速不能通过改变公式、方向、样本、成本、交易规则或评判阈值来达成。因子实现进入研究执行前，仍遵循 Step2 研究者审阅、修复复审、确定性/一致性验证的既有顺序。

## 2. 当前工作基线

- 本次检查目录：`/Users/humphrey/projects/factor-factory-knowledge-reuse-20260907`。
- 分支：`codex/knowledge-reuse-20260907`；HEAD：`525d4656`。
- 该目录有大量既有暂存、未暂存和未跟踪改动，涉及 Ultimate、Step3–5 及研究实例。HEAD 不能单独代表当前运行代码。后续工程改动必须基于实际工作树内容继续，并记录所测文件版本。
- 已安装的 Step3、Step4、Step5 技能与该目录对应技能文件逐字节一致。Ultimate 技能存在差异：已安装版本额外说明 Miner 队列接入及本机默认工作副本。不能只凭技能名称认定所有副本相同。
- 本次使用的解释器为 Python 3.14.3。该解释器的初始模块搜索路径不能解析 `factorforge_data_api`；这只是本次解释器的依赖发现结果，不证明 Data API 服务、其他环境或研究机不可用。

## 3. 已核实的工程资产

| 资产 | 本次观察 | 证据位置 |
| --- | --- | --- |
| 算子注册表 | 35 个规范条目；34 个声明支持 pandas，18 个声明支持 qlib；`where` 声明不支持 pandas。这是注册能力统计，不是 35 个算子全部验证通过 | `factor_factory/formula/registry.py` |
| 默认加速内核 | 已有部分 NumPy 时序内核及回退开关；参考实现、优化执行与实验引擎已有区分 | `factor_factory/formula/kernels.py` |
| 正式因子值复用 | 已有来源分类、身份检查、文件绑定与正式值读回接口 | `skills/factor-forge-step4/scripts/run_step4.py` 的 `evaluate_reuse_gate`、`resolve_existing_step4_formal_reuse` |
| 回测公共数据 | 已有 `backtest_base_daily_controls_v1` 缓存读写，以及供评估后端消费的 shared evaluation context | 同文件的 `_load_backtest_base_cache`、`_write_backtest_base_cache`、`build_shared_evaluation_context` |
| 收益时序 | 交易日历对齐及停牌导致的标签缺失已有针对性测试 | `factor_factory/data_access/step4.py`、`tests/test_factorforge_step4_calendar_labels.py` |
| 指标来源 | 已有 local-IS 自定义主评估器映射，保留 net、成本、零成本反事实和未恢复回撤的状态 | `factor_factory/primary_evaluator.py` |
| Step5 质量控制 | 已有后端证据质量检查、身份检查及归档前阻断 | `skills/factor-forge-step5/modules/evaluator.py`、`skills/factor-forge-step5/scripts/run_step5.py` |
| 性能观测 | 已有阶段计时、算子计时、因子复用和 wrapper 命令起止时间汇总 | `factor_factory/performance/timing.py`、`scripts/run_factorforge_performance_profile.py` |

因此优先延续、验证和补齐这些资产。历史文档提出的完整回测基础数据复用目标，不能仅凭当前 daily-controls 缓存接口存在就视为已经完成；标签、过滤表、日历、成本输入以及跨分支复用需要逐项核实。

## 4. 本次已运行的检查

在上述工作副本执行现有确定性测试：

```bash
python3 -m pytest -q -p no:cacheprovider \
  tests/test_formula_parity_fixture.py \
  tests/test_formula_reference_pairwise_alignment.py \
  tests/test_factorforge_step4_calendar_labels.py \
  tests/test_step4_factor_csv_policy.py \
  tests/test_primary_evaluator_bridge.py
```

结果：**32 passed in 1.72s**。

覆盖代码生成和参考一致性、成对算子索引对齐、停牌/日历标签、CSV 输出策略、主评估器到 Step5 的指标映射及相关下游兼容行为。数据来自测试样本。这不是完整回归，也不是真实行情的吞吐测试、Step3–5 端到端验收或正式研究证明。

## 5. 后续工作队列

| 顺序 | 工作包 | 具体交付与验收 |
| --- | --- | --- |
| P0 | 建立可重复的 Step3–5 工程基准 | 固定代码、环境、输入、规格及评估规则；复用现有测试和计时设施；覆盖 operator、direct_code、hybrid 的代表路径；分开记录冷启动与缓存命中，报告总耗时、分阶段耗时、峰值内存、I/O、复用原因和正确性结果 |
| P0 | 明确 metrics 的共同语义 | 为核心指标记录来源后端、公式/版本、频率与年化、样本范围、gross/net、成本、缺失原因；保留可扩展后端指标；用可手工核对的净值/交易样本确认收益、换手、费用、回撤及恢复期 |
| P1 | 核实并补齐回测公共数据复用 | 逐项检查 label、可投资/可交易过滤、calendar、cost inputs、daily controls；同一合法身份命中时避免重建；数据、窗口、规则或文件内容变化时正确失效；不能用 Step3 样本替代 Step4 正式因子值 |
| P1 | 按实测热点完善算子 | 从代表公式的实际计时选热点；先固定参考语义与边界预期，再做局部优化；验证 NaN、并列值、极端数值、嵌套 rank、分块与恢复后的结果；记录时间和内存收益及回退方式 |
| P1 | 完善执行与恢复 | 检查列裁剪、分区读取、滚动状态、检查点和故障恢复；故障后只重算必要范围，禁止旧状态与新代码结果混用；错误信息定位到数据、算子、账户或指标环节 |
| P2 | Step5 收口与交付稳定性 | 保持 Step4 为已执行指标的来源；强化缺失/矛盾证据的拒收和消费者读回；核实幂等归档、Mac/研究机环境差异与入口一致性 |

首个工程工作包为 P0 基准与 metrics 语义核对。优化目标在同一输入和规则下测量后确定；当前尚无依据承诺具体加速倍数或生产 SLA。每项实现变更按“复现或基准 → 小范围修改 → 相关正确性验证 → 同条件前后对比 → 完成记录”闭环。
