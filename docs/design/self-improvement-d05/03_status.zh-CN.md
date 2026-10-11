# D0.5 施工状态

2026-10-11 · 本文件区分计划、实际实现和实际验证。

## 对齐结果

总入口与自改进负责人确认两层任务：机制/数学对象/响应结构/区分实验，以及真正的公式 AST 搜索。每个新响应结构做本轮前向 induction；参数域内复用需范围核对。Step3/4/5 及标准 Factor/metrics 接口不变。

历史 D0.4 保持不变；本版由 `a7449bb387b12872f7cd2900678255732edcb4ef` 新建隔离分支。最初施工不改安装环境；2026-10-11 用户另授权验收后发布并切换默认环境，既有研究 pin、结果和知识根保持不动。

## 批次进展

| 批次 | 状态 | 已有证据/待完成事项 |
|---|---|---|
| 架构/施工图 | 已对齐并提交 | `06d0d9fa`；负责人完整回读后确认与代码无实质冲突 |
| B1 可运行公式切片 | 已提交并独立复核 | `c6f9f6c5`；synthetic causal-affine 范围内真生成、变异/交叉与标准 Factor；31 项新检查通过 |
| B2 两层树 | 已实现并独立定向复核 | `84690442` + `552c10b6` + `ba33da5c`；机制动作树、多代 GP、公式空位 MCTS；B1/B2 共 54 项定向检查通过 |
| B3 原生闭环 | 合成原生3–6及下一轮数学 STOP 已验收 | `38387225`；Step6 五个实际命令 PASS，真实独立 reviewer，最终 reject/stop；不是市场 alpha |
| B4 独立使用/比较/交付 | 自写因子/GP 使用通过，进入 R36 交付；同预算市场比较未做 | 16 行字面量手算一致、6 个 GP 唯一评价；新响应结构回 Step2，拒绝把合成分数当收益 |

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

上述 B1/B2 验收结束时未改公共 Factor、research API、Formula 引擎或 Step3/4/5。未切换 runtime/研究 pin，未发布，未运行新市场研究。B3/B4 未完成；下方记录后续追加的接口修复。

## B3 独立复审与实际执行边界

首版 `ultimate_cycle.py` 已消费现有候选台账、native readiness 和 terminal feedback，能将 AST 子代送入原流程并产生 Step6 输入材料。但首轮测试使用手工 Step3/4/5 receipts 与合成指标，只能证明协议行为；这不满足施工图的原生纵向闭环。

已通过独立反例推动修复：实际被复审的 Step2 spec 覆盖完整 grammar/lineage，而非只读 base spec 的文字说明；固定说明文字时改变单位、窗口、常数、算子、深度、缺失规则、数值域或 parent 均拒绝。高分父代必须与当前数学/观测语义相符，其他机制不能借分数跳过推导；工程夹具仍是 `synthetic_only`。Hash 仅检测内容变化，不证明推导正确或评审真实。

总入口新增 11 项独立反例，随原独立数值检查共 29 项；与 B3/induction 定向套件合计 45 passed，2.83 秒。随后禁网运行搜索、分发与 Skill 路由 12 个文件：172 passed，7.98 秒。独立检查及 B3 测试进入既有离线/分发选择，提交 `7b57ae8a`；负责人修复与实际执行尚待其单独提交/验收。

分发环境差异已定位：匹配 Data API SDK 的既有隔离 venv 通过 16 项分发/路由检查；系统 Python 缺该 SDK，旧 fallback 找到不含 `runtime` 的本地 SDK，导入 PF/VV helper 失败。对应 Data API/PFVV 源码与本轮基线无差异。此轮不改全局环境或 Data API，以已有隔离环境验证；不把这次系统 Python 失败隐去，也不将它误报为新增搜索代码回归。

下一验收点是新工作区内的真实合成数据执行：生成公式 → 实际 Step3 → 独立代码复审/审后测试 → 原生 Step4/5 → 实际 metrics/Step6 材料 → 下一代。缺辨别实验时 L1 保留 Unknown；不把原生 IC 自动变成机制判决。该运行仍不是市场研究、OOS 或 self-improvement 有效性的证明。

## 2026-10-11：用户追加的旧入口源头修复

根因不是因子数据：主 Skill 已要求标准类，但 Step2 provider/bridge、smoke 构造器、Step3 生成模板和 hybrid 指南仍含旧函数约定。B3 首次实现复用了 smoke helper，同时带入旧入口和工程夹具的研究文字；原 attempt 保留，不把它改写成成功记录。

修复统一新 authoring 为 `FACTOR` 实例、具名输入和标准因子表；直接代码原样保存，不再附加 keyword/state wrapper。operator、hybrid 和显式 family 模板采用同一类入口。Step4 分钟 fast-path 对类实例不再误取旧函数。删除固定执行三日平滑/截尾/zscore 的旧 Step6 apply/debug-autoloop 脚本及 CLI：改变响应结构仍须返回 Step2 推导，不能用包装层代替研究。

标准 `BaseFactor` / `FormulaFactor`、`research_api`、因子值与 metrics 语义未改。历史冻结代码/law bytes、旧研究及其读取兼容保留。`build_direct_code_smoke_spec` 明确只构造工程夹具；真正研究使用 Step2 的实际规格。

自改进负责人已进行两次只读交叉检查：第一次找出 Step4 fast-path 与 Step6 自动 wrapper 漏口，第二次确认关闭、当前 diff 无新增阻断。136 项受影响回归通过，72 项接口/管道回归通过；可选 Polars 在已有系统环境补跑 9 + 1 项通过。最终完整离线套件为 **2524 passed、4 skipped、2 deselected，266.77 秒**，禁用网络；其中 1 项 Polars 已另行补跑通过，其余 3 项依赖显式外部 PF/VV 历史回测引擎，本轮未运行。2 项 deselected 为原配置保留的 Git 历史/untracked 导出检查。本轮没有更改这些排除条件。

本次源修复扩展了最初的代码编辑范围，但没有切换已安装的 Skill、全局运行环境或现有研究 pin。B3 须选择修复后的提交重新生成标准类，完成实际代码/推导复核，再进入原生 Step4/5；本修复本身不是 B3 验收或市场研究结论。

## B3 合成纵向执行与数学 STOP 验收

源码 `38387225` 修复了搜索适配器漏传已审 measurement profile 与已验证 Step3 执行范围的问题。总入口阅读该小幅改动后，在禁网环境独立复跑搜索套件158项通过。标准 Factor、Step3/4/5 的输入输出未改变。

V7 的独立代码复核、审后字面量数值 oracle、真实 Step3/4/5 均通过。总入口另从实际 parquet 复算：864行、36日、24个合成标的，因子值逐项等于冻结输入 close；规范化后为排序唯一的 datetime/instrument MultiIndex、float64 factor_value。合成标签满足 `y(i,t+1)=0.0001*x(i,t)`，最大浮点差约2.17e-19；35日 Rank IC约1因此只是构造结果，不是机制或市场有效性的证据。

搜索实际生成了子式 `delay((close - mean(close, 2)), 2)`，作为 measurement variant 送回Step2。研究员给出了实际判断与新观察映射：全观测时 `h(i,t)=0.5*[x(i,t-2)-x(i,t-3)]`；当前冻结夹具 `x(i,t)=a(i)+b(t)`，故子式删除全部横截面层级，同日跨标的理论常量。独立数学复核认可该结论。数值核对发现的约8.88e-16横截面差异是舍入噪声，不作为排名信息或分数。

该分支合法 STOP：原 baseline 保留为工程回归；child未进入原生Step3/4/5，score/reward/cost均为null，票据为BLOCKED且活动票据为0；另一未选子式保留为未审提案。这里已有真实研究反思和Step2推导，但 `formal_step6_completed=false`、`native_step6_executed=false`；不将材料写入冒充正式Step6运行。尚待正式Step6集成验证，以及B4独立使用、同预算比较与发布。

本次验收读取的实际结果位于 `/Users/humphrey/projects/factorforge-two-level-search-b3-native-20261010/native-success-final-evidence-v7.json`，其 `research_closeout` 指向判断、推导、handoff与journal。V1–V6失败/中间记录保留；未改市场研究、全局Skill、OOS或知识库。该文件记录可验证进度，不新增运行入口或审批服务。

## R36：正式 Step6 与独立使用补充

上节“formal_step6_completed=false”保留为当时状态。后来实际运行的正式证明为
V7 工作区 `objects/runtime_context/step6-ultimate-proof.json`：五项原生命令 PASS，
作者与真实独立 reviewer 一致 reject，下一动作 stop，未签发因子结论。新增
`native-step6-final-evidence-v7.json` 的十项 bytes/SHA 已由总入口复算；早期 paused
attempt 不改写。执行源码仍精确为 `38387225`，不回贴后来的发布版本号。

后续 `fb672f02` 修复成功结束后残留的同研究暂停提示：只清除已解决的暂停文件，
保留外部研究和失败历史。该改动连同 SDK/阶段入口由总入口复跑 122 项通过。

独立测试员使用自己的数学规格、合成数据、PriceVolumeFactor 和字面量手算，
16 行全匹配，含 8 NaN 与 1 真零；标签单独生成，metrics 正确给出 partial。
GP 实际评价 6 个新 AST、复用 2 次、拒绝重复 3 次；最优 `close-close` 不符合原
估计对象，返回 Step2 后 STOP。新响应家族在数值回调前拒绝（调用数 0）。没有
使用作者 tests/examples 作为预期答案，也没有将这次 SDK 使用称为整轮原生研究。

发行树复验修正了三项 Console 专属测试的归属，移入历史套件；两个 hosted
入口测试按实际安装组件检查明确错误。没有补回 Console、删数值测试或新加 skip。
删减包完整回归 2514 passed、5 skipped、2 deselected；其中 Polars 检查后来补跑。
最终发布包仍单独复跑并记录外层结果；真实市场比较、Linux 和通用 self-improvement
效果仍待验证。使用缺口已补到 [最小调用说明](../../research-search-quickstart.zh-CN.md)。
