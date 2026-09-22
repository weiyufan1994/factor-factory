# 源码交付验证

## 2026-09-22 内容灵活性接线收口

在当日已接收 closeout 基础上有限合入 E 的 23 个修改文件和 1 个新测试；原 KB 维护、Step4 状态与本地窗口保护保留。普通新 local IS 研究由 agent 在首次落地前一致声明适用规则，用户无需手工配置；未标记旧研究仍走原规则，不回填历史研究。Ultimate 的内容约束参考说明同步安装，主体 Skill 未增加长篇流程。

独立审查已复现并确认：真实协议 writer→validator 接线，新规则的缩减数量输入通过；未知、冲突或不适用范围不会放宽；EVO 专用路径保留严格原实现。架构师冻结后禁网复跑候选既定清单 670 passed、2 既有 deselected、0 skipped，另跑新增专项 28 passed。新增专项加入交付清单，没有新增取消选择或跳过。

合并源码和最终新解压包的完整复跑由包外接收说明记录，以上不冒充新包测试结果。实际导出、索引与消费者已验证新增学习字段和空值理由读回；临时链的 Step3/Step6 仍包含 helper、局部门控及 mock，不宣称完整、未 mock 的真实 Ultimate 研究通过。没有读取行情/OOS、修改历史结论或刷新真实索引。下面保留较早批次记录，各批次测试数不相加。

## 2026-09-22 有限增量

本版以已验收的 9 月 21 日源码包为基线，只加入已审 custom-status、KB-01 维护出口及对应测试/说明。E 内容灵活性候选和新的 IPPS 提案不在包内。Ultimate 对应维护说明已同步本机安装；其他机器仍从本包入口读取。

随后单独接收 Step6 的最小窗口读取保护：普通 local IS 在文件路径探测前返回空窗口证据，非 local 的既有读取保持不变。4 个定向离线测试经过架构师独立禁网复跑；包括真实 iteration producer 到窗口汇总边界的调用，不只是文本检查。此保护不依赖新的 E profile，也不改变历史研究记录。

KB-01 合入后、窗口保护加入前，源工程独立禁网回归：701 passed、3 skipped、2 deselected，66.65 秒。3 项 skip 需显式设置包内执行引擎路径，源检查没有启用它；不将 skip 描述为真实引擎通过。新增 17 场景和既有 55 场景亦独立复跑，但与整套存在重叠，不相加。窗口保护后的最终解压套件另行验证，不把本段历史计数冒充新包结果。实际行情、真实索引、历史研究和 OOS 未改动，没有提交或推送。

下文为 9 月 21 日基线的历史解压验收，不冒充本增量包的新解压结果。本增量的解压复跑与内容比对由交付任务另外出具，并与包同目录保存。离线测试始终只代表合成样本与代码行为，不是研究结论验收。

## 2026-09-21 基线（历史记录）

## 本轮结果

从完整 publisher 生成的 ZIP 重新解压后，运行原有 `pytest-offline.ini` 的全部 59 个测试文件：**670 passed，0 failed，0 skipped，2 deselected**，耗时 **24.85 秒**。两项 deselect 沿用清单原有配置；本轮没有新增 skip/deselect，也没有缩小测试路径。

使用 macOS sandbox 禁止全部网络连接，并禁止读写原 Factor Forge 工程、独立 Data API 工程、全局已安装 Skills、构建输入和 candidate 等副本。探针实际尝试读取原工程、安装版 Skill、candidate 以及连接网络，均收到权限拒绝；`factor_factory` 的实际导入位置为 ZIP 解压目录。测试使用该目录源码、本机已安装依赖及临时合成样本。

本次直接使用下列已安装环境，并未新建虚拟环境或重新联网安装依赖。因此这是受隔离的源码/ZIP 离线运行验收，不将它描述成一次全新依赖安装验收。

## 实际环境与覆盖范围

macOS 26.6.2 arm64，Python 3.14.3；pytest 9.1.1、NumPy 2.4.4、Pandas 2.3.3、PyArrow 22.0.0、SciPy 1.17.1、psutil 7.2.2、jsonschema 4.23.0、Polars 1.40.1。Python 自动加载第三方 pytest 插件被关闭，字节码与 pytest 缓存不写入源码目录。没有声称验证其他操作系统或 Python 版本。

覆盖清单包括知识图谱与经验读取、原文研究主体保留、Step2/3 代码审查交接和版本绑定、Step4/5 恢复、原生 Step6 入口语义、PF/VV 与 signed-A 合成数值测试。离线接口/合成回归不等于完成真实研究、经济有效性验证、正式 IS/OOS 或生产晋级。

两项既有取消选择仍为：

- `tests/test_workspace_experience_export.py::test_local_trial_patch_includes_explicit_untracked_export_source`
- `tests/test_workspace_experience_export.py::test_candidate_export_seed_rejects_lexical_symlink_and_duplicate_paths`

它们依赖历史 integration-patch 的原 Git HEAD/未跟踪文件状态。本源码交付不附带 Git 历史；完整源码 publisher 的测试正常运行。根目录 AGENTS 在 Git 路径选择和无 Git 回退选择中的覆盖、源码树/ZIP 原字节保留及清单收录均已验证。

## 实际消费与来源边界

在源码目录之外、清除 PYTHONPATH 后，仍在同一禁止网络/原工程访问的 sandbox 中实际调用：

- `query_knowledge.py --query '小波分析' --json`：命中 transient-signal 方法节点。
- 使用 README 中的完整 PF/VV 机制描述检索：实际命中包内两条经验种子；扩展记录保持 `EVENT_U_SOURCE_EXTENSION` 和 `PF_VV_AND_COMPOSITE_NOT_REPRODUCED`，不能当作作者基线已经实证复现的证据。
- `query_knowledge.py --query 'zzuncoveredq42' --json`：0 命中，没有制造经验。
- `scripts/run_factorforge_ultimate.py --help`：成功，包含 `--local-is-only`。

索引的 source_path 集合恰为两条随包经验种子的相对路径。18 份静态参考通过既有脱敏函数复制，15 个图谱索引节点与 15 份节点文件一致。两条 active 记录的原输入与修订前驱在隔离构建中通过既有校验；随包只留下两条脱敏投影，保留原记录哈希及不可在包内重放的修订来源上下文，保持 advisory/candidate，未改写原知识记录。

检索清单中的 output_path/manifest_path 记录临时构建位置，不是可移植的依赖路径；实际消费者使用包内索引和相对来源，已通过上述跨目录消费检查。历史源码仍可能包含部署示例、bucket 名称和本机路径文字。此包供私有源码试用，不宣称已经完成公开开源的许可或全面内容审查。

## 本轮改动与最终核对

D 阶段在已验收 A/B/C 候选基础上仅增加 18 份脱敏静态参考，修改 publisher 的 AGENTS 选择、对应最小测试，以及两份交付说明。没有修改研究算法、增加经验条目或开启生产索引刷新。完整测试在参考齐备后直接通过。

最终包使用同一完整 publisher 构建。与通过验收的解压副本逐文件核对：代码、测试、配置、Skill、图谱、经验种子及索引正文一致；仅两份交付说明和据此生成的 README 更新，检索清单仅临时构建路径不同。ZIP 与最终源码树再按清单逐文件核对。

原工程及全局安装目录未同步，没有提交或推送。两处三方合并方案另交架构师审核，不属于本地交付验收的自动后续步骤。
