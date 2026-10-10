# 因子搜索接口 v1

本接口把 Step2 / Step6 Council 的候选修改接到原生研究执行与反馈。
候选生成器、调度器和 Step3–5 执行器分别替换；不绑定模型供应商。
这是独立工程变更，不属于 R3 精简包，也不切换已有研究 pin。

## 对象与职责

1. `SearchContext` 冻结来源文件、研究对象、开发协议、评分规则和预算来源。
   proposer 只获得开发侧上下文；confirmation/OOS 内容不进入输入。
2. `CandidateProposal` 保存父候选、数学/观测/实现变化、typed program、公开推导、
   预期结果和证伪条件。它是提议，不能直接生成正式研究结论。
3. `EvaluationTicket` 是已预留预算的一次研究动作，引用明确的原生执行请求。
   pending / waiting review / running / interrupted 与 terminal feedback 分开。
4. `CandidateFeedback` 绑定实际原生成果与校验，按冻结规则产生一次候选分数。
   该分数不可被树节点的累计统计改写；失败和未知不产生奖励。

机制变化进入新的 Step2 分支；观测/估计变化进入 measurement/data binding 修订；
数学等价实现进入独立 parity/code review。公式参数变化通常是估计变体，不能仅因
代码很短就标成数学等价。三种实施模式 `operator/direct_code/hybrid` 均保留。

## 非阻塞循环

生成/登记候选 → 调度一次扩展 → 原子预留 trial/compute 预算 → 派发研究动作 →
原有研究角色完成 Step2/3 准备、代码审查与审查后测试 → attach ready request →
原生 worker 执行 Step4/5 → 收集反馈 →
将开发侧反馈交给下一轮 proposer / planner。

首版最多一个在途 ticket。`tick` 遇到在途任务先 reconcile，不会偷跑第二个候选。
派发成功不等于研究成功；单纯 request 文件也不构成运行证明。
原生流程仍通过其既有 Step3B review 和 Step4/5 校验。搜索接口不实现行情、标签、
账户回测或新的公式 `eval`，不会从随机行情获得市场分数。

## 搜索与恢复

异步 MCTS 每次只选择一个扩展，完整结果到达后才进入统计；旧同步 MCTS 保持不变。
调度器从不可变终态反馈重建统计，同一反馈在一次重建中只使用一次。
兄弟未尝试动作先展开，随后才沿 UCT 深入；耗尽一条深度不会阻塞其他合法分支。
`registered_queue` 用同一候选/结果接口提供对照，不称为 MCTS 或 GP。

相同原生 conjecture/state 是共享预算的边界，不由 proposer 创建或扩张。预留、ticket 和状态变更
持久化在一个事务存储中；同候选/协议有唯一动作键。完成结果回放不新增 trial。
派发前中断可使用原 ticket；派发后结果未知必须先 reconcile，不能自动盲重试。
失败、未知完成和中断保留占用，不通过换 run id 退回预算。

## 接入与验收

proposer 只提交结构化对象，原生 executor 只接明确 ticket/request 并返回证据引用。
原生已完成反馈必须绑定开发协议、数据来源、代码和 Step3/4/5 原生证明；确认集结果
不进入开发反馈，缺指标不填零，排名变化不被解释为交易换手。

测试包括：来源漂移、错误变更分类、重复候选、预算竞争、预留后崩溃、派发后崩溃、
等待审查、部分执行、终态反馈幂等、缺失/变更原生证据、Unknown 成本、确认集误入、
分支公平性、候选分数不可变、provider 替换与独立分发包导入。
工程固定样本测试始终标记 `engineering_fixture`，不证明因子有效性。

## 主研究员如何接入

入口是 `factor_factory.research_search` 和 `scripts/manage_factor_search.py`，不更改
Ultimate 的默认执行路径。主研究员是上下文、预算和原生准备的唯一写入者；候选模型
只能通过 `CandidateProposer.propose(context, max_proposals, seed)` 返回提议。
这是同一可信本地主机中的研究接口，不是隔离任意 Python 插件的操作系统沙箱。
要接外部模型，宿主只发送 `proposer_context()` 返回的公开投影，不把工作目录授予模型。

主研究员先冻结 `factor_search_context_v1`：绑定原生 Step2/measurement/Council、
原生 `research_conjecture` 与 `research_state`、开发数据范围、单次两阶段成本上限、
评分规则。接口使用原生研究协议和 Council validator 验证来源。开发 split 必须在
原生 IS 范围内；已看过全 IS 的再搜索标记 `nonblind_secondary`，不能升级成盲确认。
PIT、数据真实性以及该公开投影是否准确反映研究来源，仍由原生研究/数据审查负责。

```python
ledger = SearchLedger(workspace)
ledger.create_campaign(context)                 # 可信宿主，非 proposer
ledger.register(campaign_id, proposals)         # 或 controller.propose(provider)
controller.tick()                              # 预留 trial 与 compute
controller.tick()                              # outbox/action.json，交原生研究角色
# 原生 Step2/3、独立代码 review、审查后测试完成后：
ledger.prepare(campaign_id, candidate_hash, native_request)
execute_ready(ledger, campaign_id, ticket_id)    # 在宿主 worker 运行
controller.tick()                              # 按实际成果回读，才产生一次反馈
```

对应 CLI 子命令是 `create/register/tick/prepare/run-native/status/proposer-context`；
均显式传 `--workspace`、`--campaign`，JSON 输入用 `--input`。`tick` 不启动后台模型、
数据下载或账户执行。原生 worker 按固定命令运行已有 Ultimate `4→5 --local-is-only`。
变更数学对象或观测方法必须带原生 Step2 run/validate 证明；所有请求必须带原生
Step3B run/validate、实际 manifest/spec/handoff/input 绑定和代码审查记录。

首版内置执行连接支持已物化的日线/分钟文件。Streaming query、分区 derived state、
动态 rematerialization 和 OOS/hosted 执行会明确拒绝，需要各自的输入绑定 adapter。
不把这些路线“猜成”已验证数据，也不改造现有 Data API。默认注册的指标适配是
原生 self-quant `rank_ic_mean`（无量纲、coverage/rank_ic_count）；其他指标需原生
payload 的明确单位字段，不能把 Rank IC 分数解释为扣费账户收益。

## 中断与证据

文件派发不确定可用 `reconcile-dispatch --ticket` 幂等恢复；它只发布同一动作文件。
准备阶段被拒绝可用 `stop-preparation --ticket --actor --reason` 终结；保留 trial 和
全部 compute 预留，不产奖励。worker 在启动前原子置 RUNNING，重复调用不会重跑。
若进程在落地完整 receipt 前死亡，保持在途等待宿主核对进程和成果；接口不推断
“没收到结果就没执行”。完整 result 已落地时，后续 tick 会回读并只记一次。

SHA 验证流式读取大文件，进程内缓存用 inode/size/mtime/ctime 共同约束，变化即重算；
控制循环不反复加载分钟表。旧同步 MCTS 和原生 Step2–6 均不修改。
