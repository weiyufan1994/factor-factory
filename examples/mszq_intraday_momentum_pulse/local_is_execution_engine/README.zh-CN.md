# 本地 IS 纯执行引擎（PFVV 试用包）

此目录是 PFVV 月度适配器所需的最小、代码-only 执行引擎闭包。三份 Python 文件按原始模块名和字节内容保留；它们不是 PF/VV 公式，也不构成独立的 PFVV 复现。

## 内容与来源

来源为已冻结的 MSZQ 本地 IS 候选执行实现；本包仅分发经核对的纯代码副本，不包含行情、收益、交易账本、远端入口或研究结果。为使其可由显式模块加载器解析，三个文件必须同目录且不得改名：

- `mszq_step4_portfolio_evaluator_candidate_v1.py`
  - SHA-256: `43c03e0057dd3018f57c5f5a7a0496ad6cfc085159f2e59b6b5960d67510c901`
- `mszq_evaluation_calendar_candidate_v1.py`
  - SHA-256: `6ed49aae31336bd1ae326147e2410a73d5574ee550f2696adcddf820abb793c9`
- `mszq_v17_normalized_constraints_candidate_v1.py`
  - SHA-256: `c79a4dd127edc7c043747c9e6126a33437557d5f09bc6295e61f5595c7618e23`

## 固定执行边界

- 仅本地 IS：2016-01-04 至 2025-07-11。
- 固定单边成本：30bp；容量结论不在该代码的授权范围内。
- 该通用执行层仅接受调用方显式提供的因子值、交易日历、价格、执行价和约束；不会发现数据、访问网络或读取 OOS。

PFVV 的月末形成、十组、PF/VV 及组合信号、20 日 IC 与分量诊断由 `pfvv_monthly_evaluation_v1.py` / `pfvv_monthly_step4_backend_v1.py` 适配器掌管。不要把本目录单独称为任意研究都适用的无界回测引擎，也不要据此作收益结论。

## 显式加载

将 `PFVV_MONTHLY_EXECUTION_ENGINE_PATH` 设置为本目录，且使用模块名 `mszq_step4_portfolio_evaluator_candidate_v1`。适配器会对被加载文件身份做核验。
