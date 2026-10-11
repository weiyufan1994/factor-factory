# 两层搜索：最小使用入口

先确定经济假设、数学对象和观测映射，再选搜索动作。这里复用现有 API，
不增加回测器、因子 wrapper 或第二套 Step3–5 接口。

## 先运行现有的完整例子

在发行源码根目录，安装研究依赖后执行：

```bash
python -B examples/research_search_d05_b1.py
python -B examples/research_search_d05_b2.py
```

两者只读合成 DataFrame，不取行情。B1 展示推导范围、生成/变异、编译和标准
factor head/tail；B2 展示机制动作树、多代 GP 和表达式 MCTS 的真实执行。
完整 `build_scope()` 在 B1 文件中，B2 直接复用它；不要复制一个仅含
`induction_passed=true` 的对象代替推导。例子的分数是合成目标负 MSE，不是收益。

## 公式层最小调用契约

| 对象 / 入口 | 输入与返回 |
|---|---|
| `ForwardInductionRecord` | 假设、公开推导步骤、结论、证伪项、观测映射、响应家族、grammar 与实际暴露史 |
| `InductionScope` | 上述记录及字段/单位/时间语义、算子、常数、窗口、深度、缺失与数值域 |
| `run_expression_gp(scope, evaluator=score, seed=…, population_size=…, generations=…)` | 真正生成/变异/交叉；返回候选、逐次 trace、最优候选和停止原因 |
| `run_expression_mcts(scope, evaluator=score, seed=…, iterations=…)` | 逐步扩展 typed-hole AST；返回实际评价、复用及拒绝轨迹 |
| `compile_candidate(candidate, scope, available_columns=…)` | 检查范围并编译到已有 Formula 引擎 |
| `compute_candidate(compiled, {"daily_df": frame})` | 经过 FormulaFactor 得到标准因子表；不执行取数、标签或账户回测 |

评价回调的形状是 `score(candidate) -> float`，只有有限数值才是已知分数。
它用上表的 compile/compute 得到因子，随后调用已有分析器；真实行情的标签、
日历、固定样本和成本仍由研究方案明确提供。具体 Factor/标签/metrics 调用见
[人工接口与示例](research-interface.zh-CN.md)，数据与算子见
[SDK 手册](research-api-data-and-operators.zh-CN.md)。

最短的完整可运行调用就是 B2；它明确固定共同 warmup 后的比较窗口，检查键集
相等且数值有限，再计算负 MSE。不要按每个候选自己的非空行删样本来提高分数。
GP 的 population/generations/attempt 参数提供有限搜索范围；目前没有独立的
`max_unique_evaluations` 参数。真实研究应在现有 trial 账本中约束实际评价次数、
样本暴露和成本，不能把示例循环当作无限搜索许可。

## 机制层及返回 Step2

`run_mechanism_mcts(initial_state=…, actions=…, evaluator=…, protocol_id=…,
seed=…, total_budget=…, max_expansions=…, max_depth=…)` 接收 `MechanismState`
和 `ResearchAction`。回调 `(state, action, seed) -> MechanismEvaluation` 提供
实际实验观察和成本。B2 的 `mechanism_run()` 展示支持/反驳如何改变下一动作。
其证据是显式合成的，不是自动生成的经济解释。

新的响应结构先返回 Step2 做本轮前向 math induction。当前结构约束实现支持
causal-affine 家族，不声称覆盖任意 SDE、非线性或 Dirac alpha。标准接口能算出
一个公式，不代表该公式仍实现原数学对象；零系数和、平移不变性等额外性质需要
在本轮推导和实验中检查。

示例中的 `origin="synthetic_fixture"`、`review_decision="proceed"` 是工程输入，
不是独立评审。市场研究消费真实已审 Step2 规格，再由 `ultimate_cycle` 接入
现有 Step3–6；高分和 schema 合法都不能替代经济判断或实际代码复审。
状态与剩余范围见 [D0.5 状态](design/self-improvement-d05/03_status.zh-CN.md)。
