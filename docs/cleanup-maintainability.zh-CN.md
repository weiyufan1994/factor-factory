# 长函数清理与剩余职责

这是施工记录，不增加研究步骤或运行门槛。范围按 `packaging/research-files.toml` 的实际源码选择，长度按 Python AST 起止行（包含注释/声明）统计。测试对照、测试启动器和历史不分发代码与研究运行代码分开。

## 已拆分的主要运行函数

| 原函数 | 原长度 | 现在的职责划分 |
|---|---:|---|
| Ultimate 主编排 | 2746 | 库内准备、计划、执行、Council、结果整理；主入口 473 行。普通 IS 和托管路径分开选择。 |
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
| `factor_factory/console/web_research_plan.py::validate_plan` | 997 | 显式 Web/托管研究计划的身份、来源、公式、数据和预算联合检查。普通 local IS 的环境准备分支不导入它；旧计划消费者仍使用，保留兼容，不在本轮重写托管协议。 |
| `factor_factory/console/evo_child_runtime.py::execute_evo_child_ready` | 978 | 托管 child 执行/恢复和终局落地。普通 IS 不调用；保留旧行为，安装导入通过不代表执行验证。 |
| `factor_factory/research_org/runtime.py::validate_research_organization_runtime` | 893 | 显式研究组织模式跨任务、身份、结果的联合检查；`runtime_mode=off` 在导入前返回。后续可按对象类型拆分，不删除旧检查。 |
| `skills/factor-forge-step4/scripts/run_step4.py::main` | 683 | 核心路径仍串联上下文、计算/复用、评价和保存。输入读取、结果保存等已分离；下一步应按执行路线整理分派，不能塞入万能 context。 |
| `skills/factor-forge-step6/scripts/materialize_step6_child_revision.py::main` | 812 | 已选择修订后的旧 child 工作区构建，含普通和严格 EVO 兼容分支；不是解释指标所必需。保持既有原子落地顺序，不趁简化改变批准语义。 |
| `scripts/run_factorforge_ultimate_loop.py::main` | 747 | 旧多轮驱动器，区别于当前 Ultimate 默认入口。仍保留兼容调用；以后优先转发到当前库的同一实现，不能直接删旧参数。 |
| `skills/factor-forge-step2/scripts/run_step2.py::load_manifest_bound_dual_route_pdf_specs` | 678 | 已显式选择双路 PDF 输入的 V2/V3 兼容读取；没有该输入约定时不进入。维护重点是按输入版本拆分，保留来源忠实性和缺失错误。 |
| `factor_factory/research_org/runtime.py::build_research_org_session_prompt` | 535 | 角色提示模板选择，含大量声明文本；不是数值算法。属于显式研究组织路径，后续抽出角色模板，不改 producer 身份。 |
| `factor_factory/console/evo_child_runtime.py::prepare_evo_child_execution` | 535 | 托管 child 的路径/来源核对和准备；普通研究不使用。保留兼容分支，无新部署或执行。 |
| `factor_factory/research_org/director.py::validate_research_organization_bundle` | 524 | 显式多角色组织的计划/任务/分工联合检查；保留。后续与 runtime 按同一对象边界清理，避免再生双份 validator。 |
| `factor_factory/revision_council/pre_oos_outcome.py::validate_pre_oos_root_synthesis` | 519 | 显式 pre-OOS 选择核对，包含结果回放；不能从普通研究中无差别删掉信息边界检查。此轮只保证既有兼容测试，不作真实 OOS 验证。 |

## 单列而非隐藏的长测试和历史代码

- 随包的 `run_factorforge_metric_verifier_smoke.py::main`（1118 行）、`run_factorforge_miner_mvp_smoke.py::main`（1016 行）和 `run_factorforge_research_protocol_smoke.py::main`（611 行）是显式启动的合成测试程序。第三个还向测试提供 fixture helper；未发现研究运行库调用这三个 `main`。它们不是因子计算入口，也不能作为真实研究结果。
- `tests/fixtures/*_before_cleanup.py` 是冻结的旧实现对照，保留其原长度以避免“旧实现也一起改了”的伪一致。它们不在 `factor_factory` wheel 中。
- 原 16866 行 Host bootstrap 和 Console 服务进程 `_run_job` 等不在标准发行选择内，保留于 Git 历史/原工程；这不是声称它们已经完成重构。

## 尚待验收

Mac 新解压回归、逐模块导入、手算例子和新旧一致性只证明对应工程行为。完整普通研究执行的导入观察、Linux 真实 root/非 root、独立研究员阅读/研究试用仍须单独完成；这些缺项不由“文件变少”或“测试数量增加”代替。最终 M2 仍以施工图的完整验收范围为准。
