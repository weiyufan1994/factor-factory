# 研究核心与历史代码分离

这是施工记录，不增加研究步骤或运行门槛。本轮不仅拆函数：改变实际分发范围，并解除普通研究对托管组织/Console 的运行依赖。历史代码留在完整 Git 源码，研究发行树和 wheel 中没有这些模块。

## R3 的实质精简

与 R2 同口径比较：逐个读取实际分发树的 Python 文件，物理行数包含空行/注释；不含 Markdown，不重复计算 wheel。框架代码指 `factor_factory + scripts + skills`，不把测试削减冒充运行代码削减。

| 框架部分 | R2 行数 | R3 行数 |
|---|---:|---:|
| 研究库 `factor_factory` | 176,614 | 100,188 |
| 命令脚本 `scripts` | 67,585 | 14,401 |
| Skill 中的阶段代码 | 52,197 | 52,197 |
| 合计 | **296,396** | **166,786** |

减少 **129,610 行，约 43.7%**。独立 Data API SDK 的运行代码保持 4,001 行，不混入框架减少量。全仓库没有声称删掉同等行数；旧代码仍可通过 Git 查阅或在完整源码环境中维护。

具体分离：

- Console 的 37 个模块（41,939 行）、托管组织执行的 5 个模块（10,486 行）、Miner 的 11 个模块（4,086 行）退出标准研究分发。
- 托管记忆、EVO 执行编排及 hosted Ultimate 等 11 个文件（20,001 行）退出标准分发；普通检索、候选经验维护、GP/MCTS 和 Step6/Council 保留。
- 历史部署、生产补数、大 smoke runner 等 131 个命令脚本（53,186 行）退出。测试真正需要的合成输入迁到 `tests/helpers`，不再为几个 fixture 安装整个历史 smoke 链。Qlib 格式导出入口保留，仍可验证 instrument/calendar/provider 的转换。
- `research_org.gate` 只判断是否显式选择了托管计划；普通研究不导入 director。存在托管计划时仍执行原验证，缺少托管组件时明确报错。完整源码旧入口转发到同一个判断，不维护第二套规则。
- 根目录模块/命令改为正向选择；核心子包按职责保留。新增未分类模块不再自动进入发行。实际 wheel 逐文件与选定源码比较。
- 普通测试保留；托管兼容测试迁到 `tests/legacy`，完整源码中单独运行。没有把真实研究失败改成 skip。

本轮四个公开 SDK 文件 `factors.py`、`research_api.py`、`portfolio_api.py`、`result_artifacts.py` 以及 Step3/4/5 阶段实现与 R2 字节相同；不会靠调整账户、指标或因子表语义换取测试通过。

## 前轮已完成的职责拆分

以下长度按 Python AST 起止行统计。它们解释已有重构，不作为 R3 减少 13 万行的来源。

## 已拆分的主要运行函数

| 原函数 | 原长度 | 现在的职责划分 |
|---|---:|---|
| Ultimate 主编排 | 2746 | 库内准备、计划、执行、Council、结果整理；普通 IS 和托管路径分开选择。本轮进一步将可选模式检查前置到创建工作区之前。 |
| `_minute_derived_flow_state_adapter` | 2006 | 14 行生成入口；4 个纯计算模块的最大函数 145 行。生成的因子代码仍完整可读。 |
| Step4 `main` | 1314 | 主函数 683 行；分钟分派、输入读取、复用判定、结果保存、评价上下文、覆盖和质量分别维护。主编排仍偏长，见下表。 |
| `_has_explicit_transient_impact_model` | 946 | 多项式计算和语义关系识别分开；主判断 170 行，helper 最长 97 行。不是定理证明器。 |
| `validate_measurement_program` | 880 | 33 行入口；按数学/观测/实现/评价章节检查，最长 199 行。错误顺序及旧规则保持。 |

Step5 双实现已经合并为 `factor_factory.step5`；Step6 的结果校验、终局、日志和事实包已库化。旧脚本保留显式兼容入口，不保存第二份业务实现。对上述数值和校验重构，测试同时保留冻结旧函数作逐值/逐错误对照，另有独立手算或已知错误判据；旧函数不进入 wheel 运行模块。

## 2026-10-10 核心阶段补充拆分

此批只拆已有职责，不修改公开 SDK、因子表、账户模型或研究决策。阶段间继续传现有对象和显式参数，没有增加统一万能 context 或每因子 wrapper。

| 入口 | 此批之前 → 之后 | 拆出的职责 |
|---|---:|---|
| Step3A `build_step3a` | 582 → 359 | 数据源描述、Qlib 字段投影、实现路线描述；输入路线选择和执行顺序仍在主入口。 |
| Step3B `generate_first_run_factor_values` | 501 → 416 | 样本读取、数值/日历/排序校验、CSV 策略；计算和采样范围不变。 |
| Step4 `main` | 847 → 683 | 状态输入、共享数据读取、正式结果复用、结果保存、评价上下文、显式 child 分派。 |
| Step6 `main` | 556 → 312 | 作者机制解释的投影、仅 promotion 使用的检查、写入前失败/修订停点。 |

主函数行数下降不代表所有维护债务已消失。Step4 的执行分派仍偏长，Step3B 的性能/缓存信息构造仍占较多篇幅；这两处保留为 Claude 复审重点，不能只看函数长度判定通过。

新增独立小样本检查覆盖 NaN/真实零/排序、越界日历、三种 CSV 策略、缺数据不回退取数、local reject 不进入 promotion，以及无错误时不制造失败记录。Step4 仍对冻结旧主函数执行逐输出、逐错误比较。

## 标准源码仍超过 500 行的运行函数

以下是剩余维护债务，不把“已分类”写成“全部简化完成”。没有剩余超过 1000 行的研究运行函数；下列保留主要涉及多阶段编排/兼容检查，并非必须保持不可拆分的数值算法。

| 源文件与函数 | 行数 | 实际用途及本轮处理 |
|---|---:|---|
| `skills/factor-forge-step4/scripts/run_step4.py::main` | 683 | 核心路径仍串联上下文、计算/复用、评价和保存。输入读取、结果保存等已分离；下一步应按执行路线整理分派，不能塞入万能 context。 |
| `skills/factor-forge-step6/scripts/materialize_step6_child_revision.py::main` | 812 | 已选择修订后的旧 child 工作区构建，含普通和严格 EVO 兼容分支；不是解释指标所必需。保持既有原子落地顺序，不趁简化改变批准语义。 |
| `skills/factor-forge-step2/scripts/run_step2.py::load_manifest_bound_dual_route_pdf_specs` | 678 | 已显式选择双路 PDF 输入的 V2/V3 兼容读取；没有该输入约定时不进入。维护重点是按输入版本拆分，保留来源忠实性和缺失错误。 |
| `factor_factory/revision_council/pre_oos_outcome.py::validate_pre_oos_root_synthesis` | 519 | 显式 pre-OOS 选择核对，包含结果回放；不能从普通研究中无差别删掉信息边界检查。此轮只保证既有兼容测试，不作真实 OOS 验证。 |

## 单列而非隐藏的长测试和历史代码

- 旧 `run_factorforge_metric_verifier_smoke.py::main`、`run_factorforge_miner_mvp_smoke.py::main` 和 `run_factorforge_research_protocol_smoke.py::main` 均不再随包分发；研究测试所需的纯 fixture 已独立。
- `tests/fixtures/*_before_cleanup.py` 是冻结的旧实现对照，保留其原长度以避免“旧实现也一起改了”的伪一致。它们不在 `factor_factory` wheel 中。
- 原 16866 行 Host bootstrap、整个 Console、托管组织 runtime 及旧多轮驱动器不在标准发行选择内；不声称这些旧系统已经完成重构。

## 尚待验收

Mac 新解压回归、逐模块导入、手算例子和新旧一致性只证明对应工程行为。完整普通研究执行的导入观察、Linux 真实 root/非 root、独立研究员阅读/研究试用仍须单独完成；这些缺项不由“文件变少”或“测试数量增加”代替。最终 M2 仍以施工图的完整验收范围为准。
