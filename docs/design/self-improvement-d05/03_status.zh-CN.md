# D0.5 施工状态

2026-10-10 · 本文件区分计划、实际实现和实际验证。

## 对齐结果

总入口与自改进负责人确认两层任务：机制/数学对象/响应结构/区分实验，以及真正的公式 AST 搜索。每个新响应结构做本轮前向 induction；参数域内复用需范围核对。Step3/4/5 及标准 Factor/metrics 接口不变。

历史 D0.4 保持不变；本版由 `a7449bb387b12872f7cd2900678255732edcb4ef` 新建隔离分支。现有 R3 review 包、安装中的 Skill、runtime pin、因子研究工作区和知识根均不在本轮编辑范围。

## 批次进展

| 批次 | 状态 | 已有证据/待完成事项 |
|---|---|---|
| 架构/施工图 | 已对齐并提交 | `06d0d9fa`；负责人完整回读后确认与代码无实质冲突 |
| B1 可运行公式切片 | 已提交并独立复核 | `c6f9f6c5`；synthetic causal-affine 范围内真生成、变异/交叉与标准 Factor；31 项新检查通过 |
| B2 两层树 | 正在施工 | 需要实际机制后继动作和表达式树扩展；B1 不等于此项完成 |
| B3 原生闭环 | 未完成 | 复用现有 native 生命周期不等于新引擎已接通 |
| B4 独立使用/比较/交付 | 未开始 | 未做新市场测试，未发布 |

## 后续报告原则

每批填写实际修改文件、可重跑检查、输出样例和剩余缺口。测试通过不推导出 alpha；工程可用不推导出普遍 self-improvement。失败/中断保留真实状态，不以新文档替代实现。

## 总入口的基线检查

- 代码施工前独立回归：179 passed，7.33 秒；覆盖标准 Factor、research API、Formula parity、search lifecycle/planner、Step3 direct code、Step4 重构和 Step5 canonical 实现。
- 使用已有隔离 Python，禁用网络；命令为 `python -B -m pytest -c pytest-offline.ini -p no:cacheprovider` 加上述八个对应测试文件。这里是原能力的兼容基线，不是新搜索能力的通过证据。
- `git diff a7449bb3 -- factor_factory/factors.py factor_factory/research_api.py factor_factory/formula skills/factor-forge-step3 skills/factor-forge-step4 skills/factor-forge-step5` 为空。
- `quick_validate.py skills/factor-forge-ultimate`：通过。测试 Python 缺 PyYAML，改用已有且含 PyYAML 的系统 Python 运行该检查；没有安装新依赖。
- 补充回归：102 passed，139.87 秒；覆盖 Skill 路由、三种实现模式的 metrics、独立命名输入及组合公式历史窗口。

## 施工中独立反馈

首轮代码阅读向负责人反馈：不能用裸 induction 布尔值/引用字符串替代实际公开推导记录；不能仅比较 response-family 标签而放行同单位非线性树。B1 已改为消费有公开推导内容的合成记录及实际 AST 家族检查。真实 Step2/Step6 review 消费留在 B3，不伪装为已接通。

独立编译最初发现 50 个已接纳树中 6 个负常数表达式失败：原 parser 将负数表示为 `negate(constant)`。负责人修复为精确处理这一表示，不宽泛放行新增算子；另修复窗口/系数混用、参数变异误标和已知零分母。

## B1 实际交付与独立复核

- 新模块：`induction.py`、`typed_ast.py`、`generator.py`、`formula_bridge.py`，全部位于 `factor_factory/research_search/`；标准 Factor/Formula/Step3/4/5 源码仍未改动。
- 可运行示例：`python -B examples/research_search_d05_b1.py`。输出真实父子公式、生成尝试、编译结果及标准 factor head/tail；使用合成观测，不读市场数据。
- 总入口独立测试：`python -B -m pytest -c pytest-offline.ini -p no:cacheprovider tests/test_research_search_d05_independent.py tests/test_research_search_formula_bridge.py tests/test_research_search_generator.py tests/test_research_search_induction.py tests/test_research_search_typed_ast.py`：31 passed，0.82 秒；禁用网络。
- 其中 12 项为独立实现：6 个随机种子各生成 10 棵初始树，并对成功变异/交叉后的全部树逐 instrument 用手写数值循环比较，未复用 Formula 的数值 helper；另检查非法树的 fitness 零调用、负常数、NaN/真实零和未来扰动不影响过去。
- 当前只支持已推导的 `causal_affine` 家族，含显式截距；不是“任意公式都合法”。B1 记录只接受 synthetic_fixture，真实研究评审适配、multi-generation GP、表达式 MCTS 与机制树仍由后续批次交付。
- 负责人另报告广回归 301 passed / 1 Polars 环境失败；待取得确切测试并与基线对比，该项不记为通过。
