# Factor Forge 本地试用交付

这个包用于本地试用：离线知识检索、PF/VV 数值与执行接口测试，以及接回现有 Ultimate 的代码补丁。**它不带行情、原研报、账户流水或凭证，也不是通用生产平台。**

## 当前研究结果与试用范围（2026-09-09）

民生证券 PF、VV 及负向等权组合的原文重建已完成全 IS 收益计算和 Step5 评估：2016-01-04 至 2025-07-11，2,313 个交易日，SH/SZ、排除 BJ，月度调仓、30bp 单边成本。组合平均 Rank IC 10.67%，扣费多头年化 4.44%、Sharpe 0.337、最大回撤 −34.06%。这支持预测关联，不证明暂时过度反应机制，也不是与作者原始代码和样本完全一致的收益复制。

Step1–6 本地研究已完成，三份真实非盲复核已汇总，研究判断为 `iterate`，并已导出实际 PF/VV advisory 经验。新的模拟研究输入通过真实 Step1、Step2 consumer 均检索到了该经验，原始经济假说与数学对象保持不变：这是知识链路功能验收，不是另一个新因子实证或“RAG提高收益”的对照试验。最终包显式携带这一案例的净化摘要，不安装原始研究数据。

下列“未完成”描述是 9 月 8 日的历史修复节点，不是上述当前进度。

## 历史修复记录

2026-09-08 第一轮修正：区分原文复现、来源扩展和独立假说；0.82 仅作机械兼容分；检索合并图谱与经验，并用显式更正版本撤回无依据的风格/约束解释；增加八组条件化算子参考。PF/VV/等权组合的原文基线研究仍未完成。所有例子和测试均不能代替这项研究验收。

同日第二轮修正：Step2 缺失/空的原文路由不能再默认绕过检查；Step6 本地终止判断同时核对 journal/review 的当前研究身份及精确作者标签。后者只是本地声明一致性，不是独立环境认证。新增 PF/VV 原文重建数值核及 26 项手算/合成测试；这是本轮的主要新增示例，旧 EVENT_U 示例仍明确保留为扩展。完整说明见 `docs/research/pfvv-baseline-numerical-validation-20260908.zh-CN.md`。

同日第三轮本地修正：增加真实 agent-authored Step1 intake；本地 PDF 的 Step2 只能读取双方实际撰写的 spec，缺失时不能回落到通用价量模板，核心分歧必须显式裁决。Step1 不再自动推断覆盖 chief 的经济与数学内容；知识节点、失败假说和评估设定均传到 Step2。源仓库中 PF/VV 的真实 Step1 校验及 Ultimate Step2 已通过独立代码/工件复核；真实一天的直接代码接口也已跑通。**PF/VV 全 IS、Step4–6及研报收益复现仍未完成。**

本地试用包还显式包含 PF/VV bounded backend、64K SQLite day lookup、prepared-input assembler、daily-measurement/market-input helpers 及合成测试；它们只消费调用者提供的本地文件，不携带研究 WS、行情、持仓或收益。bounded 路线需要 `pyarrow`，已列入 requirements。WS 内的 case-specific `prepare_pfvv_evaluation_inputs_20260909.py` 不进入可移植包。

bounded backend 的 memory preflight 使用 `psutil`（不可用时有标准库回退）；requirements 已包含 `psutil>=5.9`。

PFVV 合成 engine 位于包内相对路径 `examples/mszq_intraday_momentum_pulse/local_is_execution_engine/`。设置 `PFVV_MONTHLY_EXECUTION_ENGINE_PATH` 为该目录即可运行 monthly synthetic integration；该 engine 固定 2016-01-04 至 2025-07-11 IS 日历和 30bp 单边成本，月份调仓/20日 IC 分离仍由 PFVV adapter 负责，不代表真实收益验收。

历史已评估的 **EVENT_U 直接代码延伸** 不是民生原报告 PF/VV 复刻，不能拿它的 Ultimate PASS 或结果代替本次研究。构建时可显式选择该研究的已纠正、净化、advisory-only 候选 knowledge export；未传 `--candidate-export` 时，不安装该研究案例。包不携带市场数据、净值、交易、完整结果文件或原研报，也不是 canonical admission、晋级或收益排序。

## 不需要原仓库：试知识检索

解压后在包根目录，用 Python 3.10+ 运行，不需要 API key、网络或安装依赖：

```bash
python3 knowledge-preview/query_knowledge.py --query '小波分析'
python3 knowledge-preview/query_knowledge.py --query '稀疏事件 MAD 零值 信息损失'
python3 knowledge-preview/query_knowledge.py --query 'open volume correlation low turnover payer'
python3 knowledge-preview/query_knowledge.py --query 'zzuncoveredq42'
```

前三项应出现有来源、机制和复用边界的案例；最后一项真实无命中。加 `--json` 可供 agent 消费。查询没有针对上述文字硬编码答案。

验收顺序：先独立理解自己的研报/经济假设并留存理解，再检索补充；明确哪些启发采用、哪些不适用。知识库不能覆盖原始假设。数学参考不代表实证有效；失败案例也不能自动否定当前假设。

## 不需要行情：测数值修复

若已有 numpy、pandas、pytest，可直接运行；否则在自己的隔离虚拟环境安装 `requirements-numerical-test.txt`：

```bash
python3 -m pytest -q tests/test_mszq_candidate_v2.py
python3 -m pytest -q tests/test_mszq_pfvv_source_baseline_v1.py
python3 -m pytest -q tests/test_mszq_pfvv_source_baseline_dataframe_adapter_v1.py
python3 -m pytest -q tests/test_mszq_pfvv_monthly_evaluation_v1.py
```

上述 standalone 列表不包含依赖完整 Step3 skill 路径的 `test_mszq_pfvv_source_baseline_partitioned_v1.py`；该测试只在完整 checkout 的 patch 回归中运行。包内 monthly engine 的实际路径是 `examples/mszq_intraday_momentum_pulse/local_is_execution_engine/`，例如从包根运行：

```bash
PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine" \
python3 -m pytest -q tests/test_mszq_pfvv_monthly_evaluation_v1.py tests/test_mszq_pfvv_monthly_step4_backend_v1.py
```

这些测试全部使用合成数据。本包不含行情、净值、交易或完整可复算结果文件；包含明确标为历史 advisory 的案例摘要及有限数值检查说明。候选 export 只供知识检索；PF/VV 实际全 IS 结果来自另存的研究工作区，不是运行这些合成测试产生的。不要把历史季度示例、数值修复测试或历史案例结论当作本包内置的可复算实证结果。

流式 PF/VV 接口每次消费一个显式交易日，只保留20日状态，不从目录猜测数据源。月度模块提供十组分组、下月调仓窗口与独立20日IC标签，并通过显式参数复用既有现金持仓引擎；它不是第二套回测引擎，也不自带真实行情。并列因子值采用事前固定平均秩，不能靠股票代码强拆成十组；不可估月份要显式保留。

月度模块的纯日历/分组测试可独立运行。调用既有真实执行引擎的合成集成测试需要显式设置 `PFVV_MONTHLY_EXECUTION_ENGINE_PATH` 为该引擎所在目录；未设置时该项会显示 `SKIPPED`，不能把它算成通过。源仓库验证另行提供该路径执行，不要求使用者依赖作者的私人绝对路径。

独立数值包也不含完整 Ultimate runner，因此 DataFrame adapter 的真实 Step4 caller 集成测试会明确跳过；应用补丁后的完整 checkout 中该项必须实际通过。纯数值通过、缺运行环境的跳过和真实接口集成通过分开报告，不互相替代。

## 已有 Factor Forge 仓库：试 Ultimate 集成

`ultimate-integration.patch` 面向基线提交 `525d4656eb77ba613a39b445ff72ac7eb81bbeeb`。builder 的 `build()` 只要求当前 `HEAD` 等于该 base，并不要求工作树干净；实际应用和验证 patch 时仍应使用干净 base checkout/worktree，勿覆盖正在研究的工作区：

```bash
git apply --check /path/to/ultimate-integration.patch
git apply --index /path/to/ultimate-integration.patch
python3 scripts/build_factor_knowledge_graph.py
python3 scripts/run_factorforge_ultimate.py --help
python3 -m pytest -q \
  tests/test_factorforge_research_protocol_local_is_scope.py \
  tests/test_factorforge_ultimate_local_is_scope.py \
  tests/test_prepared_derived_state_hook.py \
  tests/test_primary_evaluator_bridge.py \
  tests/test_step4_parent_evaluation_memory.py \
  tests/test_prepared_primary_knowledge_projection.py \
  tests/test_workspace_experience_export.py \
  tests/test_factorforge_ultimate_knowledge_refresh.py \
  tests/test_factorforge_epistemic_retrieval_kernel_adapter_offline.py
python3 -m pytest -q tests/test_step4_data_api_contract.py -k backend_failure
python3 -m pytest -q \
  tests/test_step2_source_subject_routing.py \
  tests/test_run_factorforge_local_step1.py \
  tests/test_step2_local_agent_spec_inputs.py \
  tests/test_step6_local_terminal_rejection.py \
tests/test_mszq_pfvv_source_baseline_v1.py
```

空的 cold-start checkout 没有研究 `objects/` 或显式 candidate export 时，知识图谱仍可直接构建；此时不要强行运行 retrieval-index rebuild，因为没有 retrieval source documents 是预期状态。只有在带 `--candidate-export` 的试用包，或 checkout 已有研究 objects 时，才运行：

```bash
python3 scripts/build_factorforge_retrieval_index.py --runtime-root .
python3 -m pytest -q tests/test_factorforge_knowledge_reuse_workflow.py
```

带 PF/VV seed 的最终包中，`test_real_pfvv_candidate_seed_reaches_step_consumers_by_mechanism_without_source_substitution` 的 Step1/Step2 两项必须真实 PASS；不能 skip。它们使用机制词查询而不是 report ID，验证预测关联与未识别机制的边界，以及新研究不被历史替代。未随包安装的旧 EVENT_U 案例测试可以明确 skip。

研究入口仍是 `scripts/run_factorforge_ultimate.py`，由 `skills/factor-forge-ultimate/SKILL.md` 编排。补丁接入已有 Step4 primary-evaluator 接口；接口测试和真实回测是分开的验收项。Step6 保留工作区本地索引，并把显式 `knowledge_record` 的最小字段 create-only 投影为本项目默认知识根下的候选案例，再刷新默认索引；新研究的 Step1/2 会在 source-first 理解之后自动把它作为 advisory prior 检索。该导出明确标为候选、仅建议、仅同因子不可泛化：它不是 canonical memory、晋级或收益排序。普通本地 IS 使用 `--local-is-only`，不需要 Host 服务。

若要让一个**已经完成 Step6 且已产生 export** 的候选也随最终试用包进入新 checkout 的 Ultimate 检索，在构建最终包时显式选择它（不能用目录扫描）：

```bash
python3 scripts/build_factorforge_local_trial.py --output /tmp/final-trial.zip \
  --candidate-export 'knowledge/因子工厂/workspace_experience_exports/knowledge_record__<report_id>.json'
```

该参数只接受默认 export 目录下的单个常规候选文件；打包时会清除绝对私人路径，并记录 export SHA、原始 source record 未随包提供且无法在包内验证。应用补丁后运行上面的标准 retrieval-index 命令即可由该 export 重建索引；后续刷新也会保留它。没有该显式参数时，包不会安装任何研究案例。

如已有 `__correction_...json`，显式选择这个活动更正文件；构建器拒绝旧的已替代版本。外发时只携带纠正后的净化投影，保留更正说明，不假装能在包内重放未分发的原始历史。

`--index` 在这个独立、干净 checkout 应用并暂存补丁，不创建 commit。Step3/4 Skill 增加了缺失/热身期/零 MAD/投影损失的检查要求；不改变研报原始假设，也不把修复后的数值当作收益结论。

本次交付验收必须在干净基线 `525d4656eb77ba613a39b445ff72ac7eb81bbeeb` 的独立 clone 中实际执行上述 `git apply --check`、`git apply`、wrapper `--help`、导入检查与所列合成测试。不要用 patch 文本包含、旧测试计数、图节点/边数代替这一步；知识集仍是有限试用材料，不声称完备。

执行完整 Step3–6 仍需已有研究环境和数据接口。本包不携带凭证、不配置生产 Host，也不把离线通过当作实际研究完成。包内案例摘要不包含原始研究数据，无法仅凭摘要重放其收益；用户应使用自己有权访问的输入开展研究。旧研究保持自己的既有 checkout；不要因试用补丁而改写旧证据。

给开发者的验收重点：无命中能继续提出新方法；坏索引不假装命中；同一经验可从显式导出的索引复用；当前研究不被历史案例覆盖；未完成 Step6 时不刷新；刷新失败不破坏旧索引。实际生产因子验收仍需完整 Step1–6 研究结果。
