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
| B2 两层树 | 已实现并独立定向复核 | `84690442` + `552c10b6` + `ba33da5c`；机制动作树、多代 GP、公式空位 MCTS；B1/B2 共 54 项定向检查通过 |
| B3 原生闭环 | 已派工，未完成 | 负责人已收到真实 Step2 review/目标结构绑定、异步原生回路与跨层反馈任务；不声称已接通 |
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
- 负责人首次广回归报告 301 passed / 1 Polars binary/PySeries 失败。总入口随后完整重跑相同 12 个文件：系统 Python 为 **302 passed，7.73 秒**；原有离线 venv 为 301 passed / 1 skipped，7.50 秒（仅因未安装可选 Polars）。系统 Python 单独运行该 Polars 用例也通过。原失败记录保留，不据此宣称全机 Polars 损坏；没有改/安装依赖。

## B2 施工中复核

已修正并纳入行为测试：机制支持/反驳方向与研究动作效用分离，L1 新结构先消费 induction，预测不能同 ID 覆写，失配证据不改变终局，stop 不虚构效果调用。重复 AST 结果复用，elite 不重复评价；无效树不回传为 0 分；效果 callback 失败保留 trace 并单次停止。

独立反例又确认并修复两个归纳缺口：仅改经济机制/增加实质假设也须本轮推导；父轮已有非空 delta 的旧记录不能再次充当新记录。重复已有前提不产生额外归纳工作。这里验证的是记录新鲜性与归属路由，不是用 hash 证明数学；真实 Step2 目标/lineage 绑定仍属 B3。

总入口在 `ba33da5c` 上复跑七个新功能测试文件：54 passed，1.21 秒。独立文件另包含真实 FormulaFactor 固定窗口负 MSE、唯一 AST 实际调用次数、有效反证效用和三项归纳绕过反例。没有市场数据或正式因子结论。

总入口随后以系统 Python 禁网复跑搜索与相邻 Formula 套件：**337 passed，7.79 秒**。新七个测试及其 helper 纳入原有离线套件/分发选择，避免只在开发工作区可运行；没有引入新的发布器。

分发选择与 Skill 路由随后复跑：16 passed，2.23 秒；Skill quick validation 通过。Skill 主文未增加，只有现有自改进参考页增加两层关系、当前实现和局限。

`python -B examples/research_search_d05_b2.py` 已实际运行：

- L1 支持证据 → 深化；反驳证据 → 修订机制、`needs_induction`，修订分支的效果调用未发生。
- L2 GP：22 个唯一评价、2 次复用；MCTS：32 个唯一评价。候选经标准 FormulaFactor 计算，在固定共同窗口对合成 `x + 0.5*y` 目标计算负 MSE。
- GP 示例最优为 `(y + delay(mean(x, 3), 2))`；MCTS 示例为 `(mean(delay(y, 2), 3) + mean(delay(x, 3), 1))`。这是结构生成/数值路径证据，预算不同且仅一个合成例子，**不作为算法优劣、市场 alpha 或 self-improvement 的结论**。

当前仍未改公共 Factor、research API、Formula 引擎或 Step3/4/5。未切换 runtime/研究 pin，未发布，未运行新市场研究。B3/B4 未完成。
