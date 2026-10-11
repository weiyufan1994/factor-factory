# R36：研究核心精简与两层搜索发行

2026-10-11。包内源码版本取顶层 `bundle_inventory.json`，最终解压回归、默认环境
切换结果与统计位于交付包外层。这里记录已完成的验证与能力范围，不伪造市场结果。

## 交付内容

- 标准类入口统一为 `FACTOR`；Step2/3 的生成说明与模板一致，移除旧关键词包装及
  Step6 固定平滑/截尾自动改式入口。已冻结旧研究继续走自己的原版本。
- 机制动作 MCTS 与表达式 GP/MCTS 两层都能执行；新结构先做本轮 math induction。
  当前新增的结构约束切片为 causal-affine，不是任意非线性机制搜索器。
- 标准 `factors.py`、`research_api.py`、`portfolio_api.py`、`result_artifacts.py`
  与 R35p8 字节相同：有序唯一 `(datetime, instrument)`、float64 `factor_value`，
  NaN/真实零、独立标签、标准 metrics 和账户语义不变。
- Console、托管组织/Miner 和历史部署补数从实际源码发行与 wheel 分离；Git 历史
  留作维护，不当作新研究运行依赖。

## 实际验收

| 检查 | 结果与边界 |
|---|---|
| V7 原生 Step3–5 | 864 行合成因子，实际执行；独立代码复核与手算通过 |
| V7 原生 Step6 | 五项命令 PASS；真实独立 reviewer；reject/stop。合成 IC 不支持经济 alpha |
| 新响应结构 | `delay(close-mean(close,2),2)` 先推导；当前输入下跨截面常量，STOP，不按舍入噪声排名 |
| 独立自写因子 | 16 行与字面量手算相等；8 有效/8 NaN/1 真零；未来扰动不改过去 |
| 独立实际 GP | 6 次唯一评价，2 次复用，3 次重复拒绝；最优零式返回 Step2，未当作研究成功 |
| 解压删减包全套回归 | 前置版本 2514 passed / 5 skipped / 2 deselected；最终版本另记交付报告 |
| Step6 修复与 SDK 相邻回归 | 122 passed，包括后装 Polars 的路径；不混称完整 suite |
| 安装 wheel 导入 | 230/230 模块，零导入失败；三个人工接口/账户/结果例子通过 |

V7 正式执行 pin 是 `38387225`；发布新增 `fb672f02` 的暂停提示清理，历史证明
不反向改成发布提交。第一次低成本独立试用只跑既有演示，未达目标，不计入上表。

## 使用与仍有的工作

从 [研究接口](research-interface.zh-CN.md)、[SDK/算子](research-api-data-and-operators.zh-CN.md)
和 [两层搜索](research-search-quickstart.zh-CN.md) 可直接找到类、签名及可运行例子。
独立测试发现的“必须翻四个实现模块才能调用 GP”已补最小文档，不新增 wrapper。

运行代码约 29.64 万→17.03 万行，减少 42.6%；主 Skill 指导约减少 72.8%。
详细口径和仍存四个长函数见 [维护说明](cleanup-maintainability.zh-CN.md)。
这不是全仓库历史删除，也不是 token 账单降幅。

本轮不含新 Amihud/其他市场研究、同预算算法优劣比较、Qlib 逐笔账户等价、Linux
实测或 RL 新实现。Step6 和独立使用通过允许发布研究工具，不证明机器已能持续产出
更好的 alpha。本机切换默认版本保留旧 release 可恢复；既有研究 pin、行情、知识根
与已出结果不自动迁移。GitHub 公共主线不以内部工程历史覆盖。
