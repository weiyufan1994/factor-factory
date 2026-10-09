# Factor Forge Ultimate — 本地源码交付版

此包用于建立一个可交给其他研究者测试的源码仓库，不再需要旧版 integration patch，也不依赖原作者的 Git worktree。它包含当前工作区的源码变更，而不是只导出旧 HEAD。

2026-09-22 收口交付保留已验收的 Skill 分层、代码审查交接、原文阅读、custom backend 状态投影、普通 local IS 维护出口及窗口读取保护，并加入经独立复核的新本地研究内容灵活性修复。新研究可以选择合适的方法数量，有理由地声明没有可用经验或新想法；缺失、错误与明确空值仍区分，程序不替作者编造反思。旧研究不自动改规则，真实评审、事前信息、OOS 和晋升边界不变。本包不包含新的 IPPS 提案，也不代表已经完成真实新因子 Step1–6 验收。已审文件有限合入本机源工程，Ultimate 对应参考说明同步安装；接收者仍须使用本包入口。根目录 `AGENTS.md` 随源码和 ZIP 提供，此次仅本地私有试用，没有提交或推送 Git。

## 先看什么

- 研究入口：`skills/factor-forge-ultimate/SKILL.md`，以及同目录 `references/current-operating-contract.md`。Step1–6 的配套 skills 一并提供。
- 知识模块：`factor_factory/knowledge_context.py`、`knowledge_reference.py`、`workspace_experience_export.py`，配合 `knowledge/因子工厂/` 中的方法图谱及脱敏经验种子。
- 原文基线示例：`examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_v1.py`；同目录包含分区实现、数据接口适配、月度评价和本地执行引擎。
- 独立扩展示例：`examples/mszq_signed_a_response/`。这是 signed-A 原型，不是研报作者算法；尚不能宣称完成这条扩展的 Step3–6 或实证验证。

研究原则保持不变：先理解原文或用户思路，忠实重建作者基线；知识库提供可采纳、拒绝或仅作类比的经验；新的经济假设与数学建模必须明确标为扩展。历史 `candidate_v2.py` / EVENT_U 不是 PF/VV 复现证据。

## 安装与离线验收

解压后进入 `factor-forge/`。这是源码交付，不是独立 wheel；保留 `scripts/`、`skills/`、`knowledge/`、`docs/` 和 `examples/`，不要只复制 Python 包。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
export PYTHONPATH="$PWD"
export PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine"
python query_knowledge.py --query '小波分析'
python query_knowledge.py --query 'temporary price pressure permanent information same-sign intraday path dispersion volume-peak' --json
python -m pytest -c pytest-offline.ini
```

新研究环境最低 Python 3.11，目标覆盖 3.11–3.14；上例可换成已安装的 3.13/3.14。核心依赖固定在 pandas 2.x 范围；依赖版本统一由 `pyproject.toml` 管理，`requirements-test.txt` 仅选择测试分组。

纯 DataFrame SDK 可用 `python -m pip install .`；Step4 数值/图形依赖用 `python -m pip install '.[step4]'`；需要完整源码研究和离线测试的环境用 `python -m pip install -e '.[console,step4,test]'`。Data API SDK 仍需单独安装，例如在其已交付源码所在位置执行 `python -m pip install /path/to/factorforge-data-api`，不修改上游包或自动连接行情服务。Qlib 仅在明确选择时安装 `.[qlib]`。

安装依赖需要网络；上述检索和选定测试本身使用本地源码与合成数据。实际测试环境和结果见 `docs/publish-verification.zh-CN.md`，不把目标矩阵中尚未测试的系统或版本标为通过。可选数值后端未安装时，其测试可能明确 skip。完整分发的锁文件在重新打包时生成；本分支的依赖变更不反向修改既有 R35p8 包。

`pytest-offline.ini` 是本次交付验收清单，不等于全仓库、所有后端和云端环境都已验证。工作区专属 `test_prepare_pfvv_evaluation_inputs_20260909.py` 未分发，因为它依赖未交付的历史研究运行目录。两份 PDF fixture 以及三份包含凭据形状负向样例的历史 console/binding 测试也未分发，不属于此离线验收清单。排除规则列在下方；ZIP 顶层 `bundle_inventory.json` 记录实际交付文件及扫描时遇到的排除路径，不枚举未扫描目录的全部内容。

清单明确取消选择两项旧 integration-patch 测试：它们检查原仓库 HEAD 和未跟踪文件状态，本交付不带这些 Git 历史；新的完整源码打包器由独立测试覆盖。并非把知识库或研究流程失败改成通过。

此 ZIP 已带有仅从包内两条候选经验种子生成的检索索引，可直接运行检索。索引是可重建缓存，默认不进 Git；经验种子和图谱源码进入 Git。新 clone 缺少索引时，在该副本根目录执行以下命令即可重建，不要把路径指向生产知识目录：

```bash
python scripts/build_factorforge_retrieval_index.py --runtime-root "$PWD"
```

18 份静态参考和两条经验种子均为现有内容的脱敏副本。种子保留 advisory/candidate 状态及原记录哈希；修订关系只作为不可在包内重放的来源上下文，不冒充原记录或新研究成果。本轮没有补写新知识、刷新生产索引或导入额外研究/OOS 数据。

## 如何开展真实研究

使用支持本地 skills 的 agent，在此源码根目录打开项目，并要求它读取本仓库的 Ultimate skill，而不是继续使用其他机器旧版本的全局 skill。示例请求：

> 使用本仓库 `skills/factor-forge-ultimate/SKILL.md` 完成研究。先理解我提供的原文，再重建作者经济逻辑、数学机制和算法；知识库仅补充经验，不替换研究主体。原文基线和独立扩展分开，在同一 Ultimate 框架内推进 Step1–6。只做我指定日期的 local IS。

完整研究仍需要另行提供有权使用的报告原文、行情输入/日历/执行约束，以及实际的 agent 运行环境。包里没有行情、报告 PDF、账户凭据或历史完整运行目录；离线验收不是重新跑了一次多年回测，也不是零配置自动挖因子服务。

若选择 Data API catalog 取数，需要另外安装并配置独立的 `factorforge_data_api` 包；它不在本源码包内。知识检索、合成测试与纯规划导入不因此强制加载取数服务。这里没有用假客户端或代理数据替代真实 Data API。

普通本地 IS 使用现有 Ultimate 的 `--local-is-only` 路径，不要求先部署 Host/SoD 服务。具体输入由 agent 按 skill 准备，CLI 参数可查看：

```bash
python scripts/run_factorforge_ultimate.py --help
```

知识库当前能提供数学对象、算子、经济解释、适用条件和失败经验的候选参考，并由 Step6 的经验导出供后续研究检索。这不意味着所有算子/市场状态已覆盖，也不证明知识检索已经提升样本外收益。空命中是合法结果。

## 交付选择与排除项

- 源码选择范围：`factor_factory/`、`scripts/`、`skills/`、`tests/`、`examples/`、`fixtures/`、`docs/`；根目录仅选择 `.gitignore`、`AGENTS.md`、`pyproject.toml`、`requirements-test.txt`、`requirements-knowledge.txt`、`pytest-offline.ini`。
- 额外生成：两份根目录 README、`query_knowledge.py`、18 份静态参考的脱敏副本、两条既有 active advisory 经验种子的脱敏投影及只从这两条种子生成的索引。种子 ID 为 `RPT_pdf_11d72_pfvv_20250508_mszq` 和 `RPT_web_8596d811_20250508_mszq_intraday_momentum_pulse`；不存在额外历史研究/OOS 导入。
- 排除目录前缀：`docs/superpowers/`、`dist/`、`outputs/`、`deploy/`、`data/`、`factor_research/`、`.git/`、`caches/`。不在源码选择范围中的其他目录也不扫描。任何位置的 `.venv`、`__pycache__`、`.pytest_cache` 及 `.pyc` 不交付。
- 明确排除文件：`tests/test_prepare_pfvv_evaluation_inputs_20260909.py`、`fixtures/step1/kakushadze_101_formulas.pdf`、`fixtures/step2/sample_report_stub.pdf`、`tests/test_factorforge_console_model_broker.py`、`tests/test_factorforge_console_store_auth.py`、`tests/test_factorforge_epistemic_binding.py`。
- 入选文件若含受检查的私钥/访问密钥材料、符号链接或 `.parquet`、`.pdf`、`.pkl`、`.sqlite` 二进制数据/文档，打包器会报错，不会静默放行。本地构建输入、审查证据及安装合并草案均在交付包之外。

## 推送前的边界

此次只交付本地目录和 ZIP，没有创建 commit，也没有推送 GitHub。源码目录不带 `.git`、旧提交历史、数据、缓存目录、部署目录、研究运行产物或私钥。

建议先推送到私有仓库供测试。当前没有新增开源许可证；公开发布前需由项目所有者确认许可和内容公开范围。历史源码/测试中保留了部分部署示例、bucket 名称及本机路径文字，它们不是可用凭据，也不代表这些环境随包交付；因此不将此版本宣称为已完成公开发布脱敏的开源发行版。

可进入解压目录建立新仓库，先检查 `git status --short` 和待提交内容，再提交选定源码。若要合并回已有仓库，用单独分支审阅文件差异，不直接覆盖他人的工作区。`bundle_inventory.json` 可用于核对本地交付文件，不要求接收者沿用历史审查包。

原工作区的代码、研究结果和既有改动均保留；知识图谱/经验脱敏只发生在交付副本中。
