# 民生日内脉冲：原文 PF/VV 基线与独立 EVENT_U 扩展

## 本轮原文基线

`pfvv_source_baseline_v1.py` 实现原文 PF、VV 的日值、日历对齐的 20 日分量和等权组合；`pfvv_reconstruction.json` 区分作者定义与分析者数值约定。它不读取数据、不评估收益。运行 `python3 -m pytest -q tests/test_mszq_pfvv_source_baseline_v1.py` 可检查 26 项手算/合成边界。详细说明在 `docs/research/pfvv-baseline-numerical-validation-20260908.zh-CN.md`。

当前仅完成构造重建、数值实现和单日真实输入检查，不代表 PF/VV 全窗研究或原文收益复现完成。

## 保留的 EVENT_U 扩展示例（不是 PF/VV）

这是一个独立、纯计算的候选 successor，仅修正 EVENT_U 的两处测量数值边界：横截面 MAD=0 但并非常数时保留排序；事件基准未成熟、失效或覆盖不完整时输出诊断缺失而不是 `U=0`。

冻结参数仍为阈值 3、响应 horizon 30、历史窗口 20 / 至少 15 天；事件去重与 raw-U 公式不变。完整有效、无保留事件时为 `VALID_NO_EVENT`，其 `event_u=0`；有事件但残余压力完全消失也可以是零，仍保持 `VALID_WITH_EVENT` 身份。`INSUFFICIENT_HISTORY`、`INVALID_BASELINE` 或 `PARTIAL_COVERAGE` 均为缺失，不能参与因子排序。

`candidate_v2.py` 是窄范围测量模块，不含原实现的 PF/VV 分支或分钟数据清洗。输入是先准备好的完整 240 分钟 canonical 表（每 stock-day ordinal 0–239）。`_event_outputs` 输出可用性与事件统计，`project_factor` 只对可用行排序。没有依赖本机路径或外部服务。

安装已有研究依赖后运行 `python3 -m pytest -q tests/test_mszq_candidate_v2.py`。`recheck_projection.py --input-root <已完成候选目录>` 只读取旧 daily branch 输出进行投影诊断，不能从 raw-U 反推每只股票历史是否成熟，所以不生成新的因子值，不冒充完整 v2 重跑。

它不是原报告 PF/VV 复现，也不是收益、OOS、正式 Step4 或因子接受结论。后续需在受控 Full-IS 计算中验证基准覆盖、事件后松弛、别名排除与成本后长侧收益。
