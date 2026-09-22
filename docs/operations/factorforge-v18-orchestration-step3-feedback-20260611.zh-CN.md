# Factor Forge V18 orchestration / Step3 isolation feedback

日期：2026-06-11

反馈对象：Factor Forge Ultimate 架构师 / coder

范围：本反馈只覆盖 V15 Council -> V18 multibranch orchestration、Step3 模板隔离、worker 执行效率和 lineage artifact 问题；不评价 V18 alpha 结论，不要求 data 组变更，不启动 clean data、search worker 或 official promotion。

## 1. 结论

这 5 小时里，真正的 alpha 研究推进不足，主要时间花在 orchestration / worker debug / artifact lineage 修复上。

当前已经确认：

- Step3 基准脚本没有重新混入 moneyflow/V18 因子代码。
- `run_step3.py` / `run_step3b.py` 仍按模板隔离机制工作：正式执行前复制 report-local runtime 副本。
- V15/V17/V18 的 direct-code 因子逻辑在 law registry / derived-state 模块中，而不是写进 Step3 基准 runner。
- V15 Council 已完成并 finalize，V18 multibranch synthesis / approval / materialization 已完成。

但还有 framework 层面的效率问题需要架构师解决，否则后续每次复杂 child / multibranch 都容易把研究员时间消耗在排障上。

## 2. 已发生的问题

### 2.1 Council 到 child materialization 前缺少强 preflight

V15 Council 完成后，主 agent 生成了 V18 multibranch synthesis：

- V18A exploit: `miller_flow_v18a_absolute_long_edge_gate_v1`
- V18B exploration: `miller_flow_v18b_first_passage_repair_edge_v1`
- V18C exploration: `miller_flow_v18c_crowding_filtered_repair_v1`

三条 law 都通过 synthesis validator，并写入不同 hash：

- V18A: `13641638a3b29f54a59aca9c29eca496c64fc9013aac0ca08f95e77dee1a4feb`
- V18B: `3204ff14f6b67022c9fe35d07b19f2e20623d47654b3cf04f62b30089f0dca5e`
- V18C: `a261f93b442197c0cfa55b887b7e9c180e516bca4022eba6e7f39e69dfab45a0`

approval bridge 也通过，但 multibranch materialization 第一次失败：

```text
BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_FAILED
BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED
```

直接原因是 V15 parent 缺少 `alpha_idea_master`：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/alpha_idea_master/alpha_idea_master__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20__a__a__16115b__28__V15_REPAIR_CONF_FP_20260610.json
```

继续追溯发现 V15 的 parent V14 也缺少 `alpha_idea_master`，再上一层 V11 child 才有完整 alpha idea。

这说明当前 materialization 前没有先检查：

- immediate parent 是否有 `alpha_idea_master`
- parent lineage 是否完整
- 如果历史 child 缺少 alpha idea，是否存在可审计的 ancestor repair path
- repair 后是否写入 source path / hash / reason

### 2.2 缺少正式 lineage repair 工具

本次只能做 report-local 窄修：

- 从 V11 ancestor 继承 alpha idea 到 V15 report id。
- 写入 `lineage_repair` 字段。
- 记录 source sha:

```text
64d5a593c8994c5d2c950e782ad513325cda57f39822b076f01694a435b9f372
```

该修复没有改变 formula、data、clean data、official promotion，也没有改 alpha 结论。但这种修复不应靠研究员手动完成，应该有正式脚本和 validator token。

建议新增：

```text
scripts/repair_factorforge_report_lineage_artifacts.py
```

至少支持：

- 只修 report-local identity wrapper，不修改 economic hypothesis / formula / metrics。
- 明确 source ancestor report id。
- 写入 source artifact path、sha256、repair reason。
- 输出 repair report。
- validator 能识别 `lineage_repair.status=pass`，否则 child materialization BLOCK。

### 2.3 worker 远程命令执行过于脆弱

这次大量时间消耗在 SSM quoting、远端路径、inline Python / shell 包装、stderr 截断和重复探测上。

建议架构师提供统一 worker execution wrapper：

```text
scripts/run_factorforge_worker_task.py
```

或等价机制：

- 本地生成参数 JSON。
- 上传到 worker 固定 runtime path。
- worker 只执行 repo 内脚本，不执行长 inline shell。
- 自动写 command report：
  - instance id
  - repo path
  - git sha
  - python path
  - stdout/stderr path
  - rc
  - started_at / ended_at
  - side-effect declarations

这样研究员不用反复处理 shell quote 和远程环境细节。

### 2.4 缺少 worker resource guard

本次 V18 child materialization 成功后，没有继续跑 child Step3B/Step4。原因是 true worker 上 data 组 backfill 仍在运行，占用资源约：

```text
CPU ~= 104%
MEM ~= 38.8%
```

研究员没有干涉 data 组进程，也没有启动 full Step3B/Step4。

建议 Factor Forge wrapper 在 production run 前检查：

- 是否已有 data backfill / Factor Forge worker process。
- CPU / memory 是否超过阈值。
- 当前任务是否拥有 lock。
- 若不可运行，应返回：

```text
BLOCK_FACTORFORGE_WORKER_RESOURCE_BUSY
```

并写明阻塞进程、pid、cpu、mem、command、建议重试时间。

### 2.5 framework summary 仍需要更强的一键证据

研究员现在仍需要在多个 artifact 间拼接：

- Council result collection
- Council summary
- derivation appendix
- synthesis
- approval report
- materialization report
- child executable spec
- Step3B metadata
- Step4 backend / qlib status
- side effects

建议增强已有 summary 工具或新增：

```text
scripts/summarize_factorforge_multibranch_lineage.py
```

输出一份只读 summary：

- parent / child report id
- selected law id
- formula hash / code law hash
- Council status
- synthesis status
- approval status
- child materialization status
- child Step3B/Step4 status
- qlib native / not_applicable reason
- derived state source
- daily_basic/backtest_base reuse proof
- clean/search/official side effects

## 3. Step3 基准脚本复查结论

本地复查结果：

```text
git diff -- skills/factor-forge-step3/scripts/run_step3b.py
```

结果为空。当前 `run_step3b.py` 没有未提交 diff。

搜索结果显示，Step3 runner 只包含通用 direct-code law 解析：

```text
resolve_direct_code_law_contract(...)
resolve_moneyflow_law_contract(...)
direct_code_law_id
direct_code_law_hash
```

V15/V17/V18 的具体逻辑位于：

```text
factor_factory/factor_laws/moneyflow/derived_state.py
factor_factory/factor_laws/moneyflow/registry.py
```

这符合目标边界：Step3 runner 是 framework/template，因子版本逻辑进入 law registry，不直接污染基准 Step3。

验证命令：

```bash
python3 scripts/run_factorforge_step3_template_isolation_smoke.py
python3 scripts/run_factorforge_step3_law_qlib_knowledge_smoke.py
```

结果：

```text
run_factorforge_step3_template_isolation_smoke.py: ACCEPT
run_factorforge_step3_law_qlib_knowledge_smoke.py: ACCEPT
```

其中 template isolation smoke 证明：

- `run_step3.py` 被复制到 report-local runtime path。
- `run_step3b.py` 被复制到 report-local runtime path。
- canonical Step3 runner 不作为 per-report 可变实现直接修改。

law/qlib/knowledge smoke 证明：

- V15/V17/V18 law 能从 registry resolve。
- direct-code derived-state 小样本执行正常。
- direct-code child 的 qlib native 可以标记 `not_applicable`，不再被误判为缺配置。

## 4. 5 小时时间消耗复盘

这是近似复盘，不是精确计时器日志。

| 模块 | 估计耗时 | 说明 |
| --- | ---: | --- |
| repo / worker / installed skill 状态重建 | 25-35 分钟 | 确认当前 branch、HEAD、dirty tree、true worker 路径、已提交的 Step3/direct-code/qlib 修复是否生效。 |
| V15 Council result / summary / appendix / Step6 finalize | 35-45 分钟 | 整理 5 个 real-agent result、finalize Council、确认 Step6 attached 和 validator pass。 |
| 主 agent synthesis / multibranch approval | 35-45 分钟 | 将 Council 结论转成 V18A/V18B/V18C 三分支 synthesis，跑 approval bridge。 |
| worker SSM / shell 包装 / 远程验证 | 45-60 分钟 | 多次远端执行、quote/path/stdout 问题处理，这是最不应该占用研究时间的部分。 |
| multibranch materialization BLOCK 定位 | 40-55 分钟 | 从 materializer blocker 追溯到 V15/V14 缺 `alpha_idea_master`，定位到 V11 ancestor 可继承。 |
| report-local lineage repair + materialization retry | 25-35 分钟 | 做窄修、记录 source hash、重跑 materialization 成功生成三个 child。 |
| worker resource check / 停止继续 Step3B/Step4 | 15-25 分钟 | 发现 data 组 backfill 正在占用 worker，决定不干涉、不启动 full run。 |
| Step3 clean boundary 复查和反馈沉淀 | 20-30 分钟 | 本文档、template isolation smoke、law registry smoke。 |

合计约 4.0-5.5 小时。

更关键的是比例：

- 实质研究推导和 synthesis：约 25%-30%。
- framework / worker / artifact lineage debug：约 70%-75%。
- V18 empirical Step3B/Step4 production result：0%，因为 worker resource busy，未启动。

所以，用户质疑“至于花这么久吗”是合理的。按理想框架，Council -> synthesis -> approval -> materialization 应该是一条稳定自动链路，不应让研究员在 artifact lineage 和 worker command 上消耗数小时。

## 5. 需要架构师解决的事项

### P1. multibranch materialization preflight

新增 child materialization 前置检查，至少覆盖：

- parent `alpha_idea_master` / `factor_spec_master` / `data_prep_master`
- parent lineage completeness
- synthesis / approval identity hash
- child target collision
- derived-state availability
- Step4 backend/csv/qlib policy compatibility

preflight 不通过时应 BLOCK 在正式 token，不应等 materializer 中途失败。

### P1. formal lineage repair utility

将本次手动 ancestor alpha idea repair 固化为正式脚本和 validator 合同。

要求：可审计、只修 identity wrapper、不改 formula/data/metrics、不污染 official artifacts。

### P1. worker resource lock / busy guard

Factor Forge production wrapper 启动前应检查 worker resource 和已有任务。

资源繁忙时返回 `BLOCK_FACTORFORGE_WORKER_RESOURCE_BUSY`，而不是让研究员手动判断是否该跑。

### P2. worker command wrapper

减少 SSM inline shell 和 quote 失败，统一生成参数文件、远端执行 report、stdout/stderr path。

### P2. multibranch artifact summary

提供一键只读 summary，将 parent/Council/synthesis/approval/materialization/child Step3B/Step4/side effects 串起来。

## 6. 当前边界

本轮没有：

- 启动 V18 child Step3B/Step4 full production run。
- 写 clean data。
- 启动 search worker。
- 写 official promotion。
- 干涉 data 组 backfill 进程。
- 把 moneyflow 逻辑重新写进 Step3 基准 runner。

当前 V18 状态是：Council 和 multibranch materialization 已就绪；下一步等 worker 空闲后，才应继续三个 child 的 Step3B/Step4/Step5/Step6 empirical comparison。
