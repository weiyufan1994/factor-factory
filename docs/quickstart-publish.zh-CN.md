# Factor Forge Ultimate

研究者驱动的 Step1–6 因子研究流程：理解原文或新经济假设、建立数学机制、实现和复核代码、执行评价、反思并积累可复用经验。

## 研究入口

让研究 agent 读取本仓库的 `skills/factor-forge-ultimate/SKILL.md`，从已有研究状态继续。Step1–6 的 Skill、脚本和参考文件应来自同一 checkout，不用其他机器的全局旧副本。

- 原文复现先忠实还原作者算法；独立改进另列研究分支。
- Step2 研究员独立复核 Step3 的实际代码，修复并重新评审后运行验收测试，再进入 Step4。
- Step4/5 出现实现问题时回到 Step2/3 处理；结果不好本身不等于代码错误。
- Step6 解释证据、记录失败与适用条件；知识库提供经验和联想，不代替推理，也不自动批准因子。

普通本地 IS 通过 Ultimate 的 `--local-is-only` 路径运行，不需要部署 Host 身份基础设施。研究员仍需准备真实研究记录、独立代码评审和被授权的数据。

## 安装与离线使用

Python 3.10+；本次发布实际验证环境和结果见 [验证说明](docs/publish-verification.zh-CN.md)。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
export PYTHONPATH="$PWD"
export PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine"
python scripts/build_factorforge_retrieval_index.py --runtime-root "$PWD"
python query_knowledge.py --query '小波分析'
python scripts/run_factorforge_ultimate.py --help
python -m pytest -c pytest-offline.ini -p no:cacheprovider
```

安装依赖需要网络。离线测试使用合成输入，不下载行情或运行正式研究。两项依赖旧 Git 历史的测试沿用既有排除，详见测试配置。Data API 集成测试另需安装独立 SDK，不把缺少 SDK 的运行描述为已通过。

## 数据与知识库边界

实际研究需要自行提供有权使用的原文、数据、日历、交易约束和 agent 运行环境。独立 `factorforge_data_api` SDK 不在本仓库内；SDK/目录快照应由数据负责人提供并显式绑定。本仓库不是零配置行情服务。源码中的云存储与机器位置示例不可当作真实可用配置。

知识模块位于 `factor_factory/knowledge_context.py`、`knowledge_reference.py`、`workspace_experience_export.py`。随附内容是去除原始指标和私有路径的参考投影，不包含完整研究结果。所有候选经验保持 advisory 状态；空命中和有理由的不采纳均合法。

当前可使用关键词/图谱检索；语义检索接口存在，但此公开版本不附带 embedding 模型或远端密钥，不声称开箱即用的语义召回已验收。新研究的真实写回、跨案例复用效果仍需实际研究验证。

## 本次整理

- 更新 Ultimate 与 Step1–6 的分层指令、代码评审交接、失败反馈、普通本地研究的内容灵活性和经验维护。
- 合入可移植的实现运行、PF/VV 合成数值对照、Step5 结果消费及 Step3B 模板边界修复。
- PF/VV 的 SDK 专用准备模块和远端 worker 运维脚本不在本次公开范围；分钟生产示例保留已验收的 SDK 独立版本。Mac 安装版的 SDK 专用增量另行管理，二者不可互称完全相同版本。
- 不包含行情、原始报告 PDF、真实运行/回测产物、私有运维记录、Host keys、个人环境、数据目录快照或检索缓存。原始本地研究和旧 worktree 不删除。

从现有公开 `main` 建立独立发布分支，只提交公开整理后的文件，不上传未发布的本地祖先提交。本次不重写已有公开 Git 历史，也不授予新的开源许可证。

工程验收不等于完整新研究通过，更不等于因子有效、OOS 通过或已晋级。
