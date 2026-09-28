# D0.4 初版预览

发布日期：2026-09-28。定位：可下载、检查和离线测试的研究工具初版；不是正式部署或有效 alpha 声明。

## 核心目标

算法帮助研究员发现、实现和检验数学机制，不让数学解释为搜索结果服务。

沿用 Ultimate 的 Step1–6：先理解原文或经济假设，再前向推导数学对象，随后实现与独立复核代码、检验预测、反思证据。每一轮新响应结构重新进行数学推导；SDE 按问题适用性采用，不强制套用。原文基线与自主扩展保持分开。

## 此初版包含什么

| 部分 | 已交付范围 | 尚不能宣称 |
|---|---|---|
| Skill | Step2/3/6/Ultimate 的候选推导与反馈指引，可选 Math Derivation Tutor | 已替换用户全局安装版，或 Tutor 是正式证明系统 |
| GP／符号表达式 | 因果线性响应窄语法、参数／结构变异、交叉、数值拟合与独立卷积检查 | 通用符号回归或论文系统复现 |
| MCTS／决策 | 同协议有限动作、预算、成本、探索／利用、STOP 和恢复 | 一定优于简单搜索，或可无约束搜索任意公式 |
| Ultimate 接线 | 显式请求运行、研究材料交付、真实研究员反馈保存、幂等恢复 | 自动接受反馈、更新全局策略或派发下一轮研究 |
| 经验模块 | 可选独立 advisory root、经验版本检查、待复核出口与检索接口 | 公开了私有经验库，或已证明经验提升跨任务效果 |
| 测试 | 合成输入、失败路径、因果／时序语义、预算和既有入口回归 | 行情回测、OOS、收益或完整自改进效果验收 |

研究反馈到下一任务的已审策略更新，以及新因子完整流程的实际效果验证，仍是后续工作。RL 按原路线后置。不会因搜索可运行便默认开启算法。

## 快速试用

使用本分支同一 checkout 的代码和 Skill；依赖安装方法见根目录 README。安装依赖后，在仓库根运行：

```bash
export PYTHONPATH="$PWD"
export PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine"
python3 scripts/build_factorforge_retrieval_index.py --runtime-root "$PWD"
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -c pytest-offline.ini -p no:cacheprovider
python3 scripts/run_factorforge_ultimate.py --help
python3 scripts/run_hybrid_response_gp.py
python3 scripts/run_hybrid_research_mcts_demo.py --help
```

GP 演示只使用合成数据，不运行因子回测。实际研究继续从 `skills/factor-forge-ultimate/SKILL.md` 开始，先做原文／假设与数学机制工作；不要把工程演示的假设当作新研究的经济事实。

`--hybrid-research-adapter-only` 和 `--hybrid-research-response-only` 是显式接线入口，不能替代正式 Step2/Step6 的研究判断。新的运行目录由使用者提供，不复用他人的研究结果目录。

## 源码与发布边界

本分支在已公开源码提交 `09f68ce5770ae16d4a80552b2b0e7cee0d2b4f2a` 上有限合入可移植实现；不合并本机私有工程提交历史。保留已公开的环境占位配置，新增内容不包含密钥、行情、论文 PDF、云端运行配置或私有研究结果。

为保证冻结合成 driver 的输入可校验，附带 W11 原问题、合成预设和数学规格原字节；它们是工程输入，不是真实市场数据。数学规格中的阶段状态属于历史时点，内部原始研究员记录未随包发布；此初版不据此宣称独立真实研究审查可在公开包内完整重放。W04 施工说明同样是设计参考，不代表所有规划已经实现。

内部 W08/W09/W11 运行归档、原始 agent 对话和评审记录不随本次提交发布。测试中的小规模合成 fixture 不属于这些历史研究产物。已有公开 Git 历史不重写；此次也不授予新的开源许可证。

本次发布不改变 `main`、全局 Skills、现用 runtime、私有知识库、数据和正在开展的非流动性因子研究。

## 发布验证

完整离线清单和公开副本检查结果见 [验证说明](../publish-verification.zh-CN.md)。单元测试通过与完整真实因子研究通过、机制有效、自改进有效是不同结论。
