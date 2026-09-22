# signed-A 示例

这是一个可移植的纯代码候选示例，属于独立扩展，不是作者报告中的 PF/VV 算法复现。

输入为包含以下列的日截面表：`ts_code`、`trade_date`（`YYYYMMDD`）、`pf_daily` 和 `baseline_eligible`。实现只在同一交易日、且 `baseline_eligible=True` 的横截面上计算 `score=-sample-z(pf_daily)`；被排除行和缺失值保持缺失。

常数横截面（包括全为零）会标记为 `NONDISCRIMINATING`，并将有限值分数置为 0，不把它误判为缺失；样本不足则标记为 `MISSING`。

本示例仅通过合成数据测试验证，属于 prototype；它不表示 Step3–6 已完成，也不构成经验数据验证、正式晋级或生产交付。
