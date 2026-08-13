# Factor Forge Epistemic Evolution V2 合同

## 1. 目的与边界

EVO V2 让 Factor Forge 在不改写研究宪法的前提下，从当前研究的矛盾和历史研究经验中提出更好的问题、数学机制与区分性试验。

它不是 self-modifying Agent，也不是以回测分数为 reward 的自动调参器。EVO V2 永远不得自动修改：

- Skill、validator、角色权限和 canonical-write 权限；
- estimand、证明阈值、OOS 规则、trial budget 与 multiplicity policy；
- 已冻结的经济假设、measurement program 或历史证据；
- factor verdict、正式 promotion 或 child execution authority。

一句话原则：

> 机制是检索主键，状态是证伪坐标，事件是带 provenance 的历史证据；经验改变问题与试验，不改变宪法。

## 2. 两条分离的闭环

### 2.1 当前因子的认识论闭环

```text
BIND
-> PREDICT
-> OBSERVE
-> DIAGNOSE | VALIDITY_QUARANTINE
-> QUALIFIED_CONTRADICTION
-> INVERT
-> BACKPROJECT
-> RETRIEVE
-> DIVERSIFY
-> PREREGISTER_CHILD
-> PROPOSE_REVIEW_ONLY
-> HUMAN_APPROVAL
-> CHILD_WITH_FRESH_SEALED_OOS | KILL_AND_LEARN
```

### 2.2 跨因子的经验闭环

```text
Host terminal outcome
-> immutable historical episode
-> candidate conditional/structural lesson
-> independent review
-> Host CAS promotion
-> mechanism-first retrieval
-> source-to-target transfer mapping
-> preregistered research use
-> transfer-use receipt
```

两条闭环不可相互短路。历史经验不是当前因子的证据；当前因子的 Council 也不能自行把自己的叙述晋升为 canonical memory。

## 3. Prediction Registry 与反馈资格

在读取用于诊断的收益结果前，必须冻结 preferred、mechanism-distinct alternative 与 null/alias 三类预测。每条预测至少绑定：

- model/hypothesis identity；
- expected metric signature、方向、形状、horizon 与 conditioning set；
- materiality floor、区分对象、falsifier；
- preregistration path/file-byte SHA-256；
- `uses_oos=false`。

观测偏离不能直接触发机制扩写。它先进入 `LOWER_LAYER_QUARANTINE`，逐项排除 implementation、data integrity、information set、measurement 与 alias/control 错误。只有同时满足以下条件，才能标记 `QUALIFIED_CONTRADICTION`：

- 信息时点合法；
- 偏离对应预注册预测；
- 未超 trial budget，且 multiplicity 已控制；
- 在 purged IS 中复现并超过预注册 materiality floor；
- 能区分至少两个竞争模型；
- lower layers 全部 CLEARED；
- 没有读取、重用或重新命名 sealed/consumed OOS。

大 residual、漂亮图形、多数 Council 意见或历史高分都不构成 qualification。

## 4. Dirac-style 最小机制增量

对已 qualification 的矛盾，EVO V2 只允许两种结果：

1. `MINIMAL_MECHANISM_DELTA`；
2. `NO_DERIVED_LAW`，即在当前预算和识别条件下无法诚实导出新定律。

最小扩展用公开推导记录表达，例如：

```text
K'(M, Z; lambda) = K(M) + lambda G(M, Z)
lim(lambda -> 0) K' = K
```

必须明确缺失项、增加的数学对象、被破坏的 invariant/boundary、保留与删除的信息、复杂度增量、移除项后的恢复试验、至少一个相对于 baseline/null 的独有预测，以及更大扩展为何被拒绝。estimand、阈值和 trial budget 不能借此改变。

数学增量必须反投影到经济机制：actor、action、binding constraint、payer、receiver、payoff/profit-transfer equation、persistence、capacity、observable proxy、negative control、counterfactual 和 disappearance condition。无法找到合法 proxy 或区分性试验时，只能保留 hypothesis，不得声称 `payer_validated`。

## 5. 三层经验对象

### 5.1 `structural_lesson`

记录跨 episode 可挑战的结构：payer/constraint、estimand、数学对象、invariant/boundary、observation map、predicted signature、falsifier、counterexample 与 reuse boundary。

经验归纳型 structural lesson 的 canonical 晋升，除严格 identity/institutional proof 外，至少需要两个独立 episode/identity、一个 counterepisode 或 negative control、invariance audit、独立 reviewer 与 Host CAS promotion。

### 5.2 `conditional_realization`

引用 structural lesson，只记录因果性的 enabling、suppressing、aliasing 或 challenging condition、可观测 diagnostic、expected interaction signature 与 falsifier。它不是“牛市用 A、熊市用 B”的 regime selector。

### 5.3 `historical_episode`

Host-signed immutable fact：窗口、资产、制度、参与者结构、事件时间线、带定义和 provenance 的 state variables、predicted-vs-observed signature，以及 economic/math/measurement/implementation/trading-economics 分层 verdict。

Episode 没有 normative authority；它不能自动选路、kill 当前模型或晋升 structural claim。

## 6. 机制优先的经验迁移

检索前先完成当前因子的 blind derivation，并从 frozen measurement program 生成 mechanism fingerprint。检索至少覆盖：

- `structural_isomorph`；
- `cross_math_analogy`；
- `near_miss_failure`；
- `direct_counterexample`；
- `historical_episode_context`。

结果排序不得使用历史收益分数。市场状态/事件只作为 universality stress axis 和 tie-break evidence；除非当前经济模型预注册了 state dependence，不得按 regime label 直接路由。

每个命中必须形成 source-to-target mapping：payer/constraint、estimand、mathematical object、invariant/boundary、observation map、preserved invariants、broken assumptions、transferred prediction、distinguishing test 与 disposition。至少应带入一个反例或反类比。

没有 admissible memory 时，必须显式记录 `COLD_START_NO_ADMISSIBLE_MEMORY` 和 hash-bound 检索证据；不得为满足 schema 伪造经验。

## 7. Tension Ledger 与“高分猎手/矛盾侦探”

EVO V2 不以高 IC 或 Sharpe 驱动自我强化。它维护：

- predicted signature 与 observed signature；
- mismatch vector 和失败层；
- 至少两个 rival explanations；
- 能区分它们的下一试验；
- `what_survived` 与 `what_failed`。

例如，Rank IC 存活但 after-cost long-side alpha 失败，应分别记为 measurement/prediction layer 存活、trading-economics layer 失败，不能把整个机制压成一个负标签，也不能因为部分存活就绕过 long-only promotion gate。

## 8. 五类正式工件

工件固定在当前 factor workspace：

```text
objects/evo_v2/<report_id>/feedback_ledger.json
objects/evo_v2/<report_id>/mechanism_delta.json
objects/evo_v2/<report_id>/economic_backprojection.json
objects/evo_v2/<report_id>/experience_transfer_bundle.json
objects/evo_v2/<report_id>/transfer_use_receipt.json
```

- `feedback_ledger`：pre-Council 的 prediction、observation、quarantine 与 qualification 证据；
- `mechanism_delta`：Council 的最小数学增量，review-only；
- `economic_backprojection`：数学增量到经济博弈的反投影，hypothesis-only；
- `experience_transfer_bundle`：blind derivation 后的机制优先检索与映射，也允许显式 cold start；
- `transfer_use_receipt`：Host 记录经验实际如何改变了问题/试验，或记录 cold start 无迁移。

每件工件使用 closed shape、相同 artifact identity、canonical JSON bytes、content hash、workspace-relative path/file-byte SHA-256 与 authority guard。逐阶段 validator 只要求当时应当存在的工件；五件套 bundle validator 只用于终局完整性，不能倒逼 pre-Council 伪造未来工件。

`NO_DERIVED_LAW` 是独立的合法终局：只保存已经 admission 的
`feedback_ledger`、Council 的 closed `no_derived_law.json` 和 staged CAS
manifest；不得为了通过五件套 validator 伪造 mechanism delta、经济反投影、
经验迁移或 use receipt。正常生产写入使用逐阶段 writer；`full-bundle` 仅用于
已有完整五件套的兼容/终局重放。

## 9. Council、子实验与 OOS

Council 只能消费 `QUALIFIED_CONTRADICTION`。Proposal 必须包含 EVO V2 intake，并继续满足原有 measurement program、formula identity、public derivation 与 no-canonical-write guards。

任何 derived law 都是 `review_only`：

- 不自动改代码或 Skill；
- 不以分数、reward 或多数票选中；
- 先经主代理 synthesis 与显式 human approval；
- child 使用新 identity、新 trial ledger 与 fresh sealed OOS；
- consumed OOS 只作为 historical episode，不得再次用于搜索或新 child promotion。

若没有可区分且可实现的最小增量，正确结果是 `NO_DERIVED_LAW` / `KILL_AND_LEARN`。

## 10. 验收含义

EVO validator PASS 只证明工件和权限边界有效，不证明因子有效。以下状态必须分离：

- EVO protocol PASS；
- Council proposal valid；
- factor-proof `ACCEPT|REJECT|BLOCK`；
- memory review approval；
- canonical memory promotion；
- child execution approval。

任何一个 PASS 都不能自动推出其他状态。

## 11. 当前实现的正式顺序与真实操作边界

### 11.1 Web/console 的 pre-OOS gate

EVO V2 启用的 Web 研究在 materialization 时冻结 prediction registry、trial
ledger、threshold registration 和生命周期初态 `PREDICTIONS_FROZEN`。正式
wrapper 仍使用唯一入口：

```bash
FACTORFORGE_OOS_HOST_TRUST_ROOT=<host-private-incident-trust-root> \
FACTORFORGE_OOS_HOST_INSTALLATION_ID=<host-installation-id> \
python3 scripts/run_factorforge_ultimate.py \
  --report-id <report_id> \
  --start-step <required_resume_step> \
  --end-step 6 \
  --research-org-runtime-mode formal-complete \
  --research-org-runtime-private-root <host-private-runtime-root> \
  --research-org-runtime-trust-root <host-private-incident-trust-root> \
  --research-org-runtime-installation-id <host-installation-id>
```

上述两个 Host incident 环境变量是所有 non-dry 正式 wrapper 调用的必需控制面；
它们会在进入普通命令或 Agent container 前被剥离，只在 current-authority 与 Host
finalizer 路径使用。若同时提供 research-org trust pair，其 canonical trust-root 路径
和 installation ID 都必须与 incident pair 完全一致。

第一次运行到 Step4 后只会生成 purged-IS checkpoint，并返回
`PAUSED / AWAITING_EVO_V2_HOST_QUALIFICATION`。checkpoint 的
`qualification.status=HOST_REVIEW_REQUIRED`；它不会自动认定矛盾，也不会释放
OOS。Host 必须基于 checkpoint、预注册预测和 lower-layer clearance 接纳以下
二选一状态：

- `NO_QUALIFIED_CONTRADICTION`：原候选可以在相同 wrapper 上恢复并一次性释放
  OOS；OOS 释放后禁止在父报告上生成 revision handoff；
- `QUALIFIED_CONTRADICTION`：wrapper 只允许 pre-OOS Council；Council 看到的是
  `PURGED_IS_ONLY`，父报告不得释放 OOS。

`RUN_PRE_OOS_REVISION_COUNCIL` 在 `council-mode=auto|agentic` 下最多构建并验证
dispatch；缺少真实 Agent results 时返回 PAUSED。`NO_DERIVED_LAW` 返回
`EVO_V2_TERMINAL_NO_DERIVED_LAW`，其 factor verdict 仍是 `NOT_ISSUED`。

### 11.2 Host-only lifecycle CAS

仅 Host 可以追加生命周期。Agent 只能提供语义工件与 verifier evidence；不得
持有 runtime trust root 或伪造 Host receipt。命令的 `--evidence-ref` 是 inline
JSON evidence reference，不是裸路径：

```bash
python3 scripts/record_factorforge_evo_v2_lifecycle.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --to-state <next_state> \
  --evidence-ref '<hash-bound-verifier-reference-json>' \
  --expected-parent-sha256 <prior-lifecycle-payload-sha256> \
  --trust-root <host-private-runtime-trust-root> \
  --installation-id <installation_id>
```

合法迁移为：

```text
PREDICTIONS_FROZEN
  -> NO_QUALIFIED_CONTRADICTION | QUALIFIED_CONTRADICTION
QUALIFIED_CONTRADICTION
  -> MINIMAL_MECHANISM_DELTA | NO_DERIVED_LAW
MINIMAL_MECHANISM_DELTA
  -> TRANSFER_RECORDED | COLD_START_RECORDED
```

命令输出的 `lifecycle_sha256` 是下一次 lifecycle append 需要的 parent CAS 值。
staged writer 还需要当前 lifecycle JSON 内的 `content_sha256`；两者不得混用，
也不得用 file-byte SHA 代替。

### 11.3 逐阶段 artifact CAS

正常生产必须按状态逐件 admission，不得预写未来工件：

```bash
python3 scripts/write_factorforge_evo_v2.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --stage admit-feedback --feedback-ledger <agent-authored-feedback.json> \
  --expected-lifecycle-parent-sha256 <lifecycle-parent-sha256> \
  --expected-lifecycle-content-sha256 <lifecycle-content-sha256> \
  --expected-staging-content-sha256 ABSENT

python3 scripts/write_factorforge_evo_v2.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --stage admit-council-outcome --council-proposal <validated-proposal.json> \
  --expected-lifecycle-parent-sha256 <lifecycle-parent-sha256> \
  --expected-lifecycle-content-sha256 <lifecycle-content-sha256> \
  --expected-staging-content-sha256 <prior-staging-content-sha256>

python3 scripts/write_factorforge_evo_v2.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --stage admit-transfer \
  --experience-transfer-bundle <agent-authored-transfer.json> \
  --expected-lifecycle-parent-sha256 <lifecycle-parent-sha256> \
  --expected-lifecycle-content-sha256 <lifecycle-content-sha256> \
  --expected-staging-content-sha256 <prior-staging-content-sha256>

python3 scripts/write_factorforge_evo_v2.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --stage record-use --transfer-use-receipt <host-recorded-use.json> \
  --expected-lifecycle-parent-sha256 <lifecycle-parent-sha256> \
  --expected-lifecycle-content-sha256 <lifecycle-content-sha256> \
  --expected-staging-content-sha256 <prior-staging-content-sha256>
```

每次都从上一条 PASS 输出读取新的 `staging_manifest.content_sha256`。前两步
只在 lifecycle 分别达到 `QUALIFIED_CONTRADICTION` 和 Council 的二选一终局后
运行；`admit-transfer`/`record-use` 只属于 `MINIMAL_MECHANISM_DELTA` 分支。
`record-use` 只 admission core Host use claim；它本身不是实际使用已验证。进入
memory admission 或声称经验真正改变研究前，还必须由 memory runtime 生成真实
before/after question/test change receipt；仅填写 `generated_test_id` 不够。

完整的 minimal-delta 分支可重放：

```bash
python3 scripts/validate_factorforge_evo_v2.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id>
```

这个 PASS 仍只表示 EVO 工件有效，输出固定保留
`formal_factor_verdict=NOT_ISSUED`、`canonical_write_allowed=false` 和
`child_execution_allowed=false`。

### 11.4 外部 human 与 fresh child OOS

外部 human approval 只能发生在 lifecycle 已达到
`TRANSFER_RECORDED | COLD_START_RECORDED`，且 staged manifest 已完整记录
feedback、Council outcome、transfer 与 actual-use 四个事件之后。
`MINIMAL_MECHANISM_DELTA` 仍只是 review-only 数学增量；此时桥返回
`WAITING_FACTORFORGE_EVO_TRANSFER_USE_RECORD`，不得提前生成 child handoff。

pre-OOS bridge 不依赖、也不得伪造 post-Step6 `research_iteration_master`。它只验证：

- canonical pre-OOS root synthesis 与 outcome verifier；
- selected raw result 和 staged delta/backprojection；
- 完整 transfer/use bundle；
- workspace 内 Ed25519 external-human receipt；
- out-of-band human trust manifest pin；
- Host 已 CAS 登记且仍 fresh 的 child sealed OOS allocation。

Host 分配 OOS 时不得让调用方提交 `dataset_snapshot_sha256`、release token 或
carrier hash。唯一生产入口读取 Host-private carrier，重放已签名的 selected
revision 和父报告受保护 evaluation contract，在私有目录推导完整 panel 后才计算
raw/derived/token 三类 hash，并将 closed build authority、日历与 universe binding
写入 Host 签名 receipt，再原子 CAS allocation registry：

```bash
python3 scripts/allocate_factorforge_evo_child_oos.py \
  --workspace-root <factor_workspace> \
  --allocation-id <allocation_id> \
  --report-id <child_report_id> \
  --parent-report-id <parent_report_id> \
  --oos-start <YYYY-MM-DD> --oos-end <YYYY-MM-DD> \
  --sealed-oos-carrier <host_private_carrier> \
  --sealed-oos-private-root <host_private_root> \
  --expected-registry-sha256 <current_sha_or_ABSENT> \
  --trust-root <host_trust_root> --installation-id <installation_id>
```

旧 direct-hash Python helper 仅保留为显式 `legacy_test_only` fixture；其 allocation
authority mode 不能通过正式 child/release gate。任何 workspace 内遗留的隐藏 OOS
panel temp 都必须 BLOCK 并由 Host 审计，不能静默恢复或覆盖。

任何未授权读取、计算或落盘触及冻结 OOS 后，必须立即通过
`scripts/record_factorforge_oos_exposure_incident.py` 写入 create-only 的
`oos_exposure_incident__<report>.json`，并同步登记到 workspace 外的 Host 签名、
append-only negative registry。该事件只表达 `NEGATIVE_EVIDENCE_ONLY` 与
`formal_oos_eligible=false`；它不是 release、consume 或科学裁决。marker 的存在本身
（包括无效 JSON、目录、正常或 broken symlink）必须在 allocation、preregistration、
release authorization/preflight、finalizer 与 consume 前 BLOCK；Host registry 已登记后，
删除或篡改公开 marker/registry 仍须 fail closed。事故时 runner 字节若未冻结，不得用
事后修补代码冒充原始 lineage；应写 create-only provenance addendum，明确
`CURRENT_REMEDIATION_RECONSTRUCTION_ONLY`。验证器 PASS 不能恢复 OOS authority，
后代也不得通过改 report id 洗白任何 root-to-active lineage 上的 exposure 事件。

正式事故登记必须给出完整、可重放的 Host 上下文与固定时间：

```bash
python3 scripts/record_factorforge_oos_exposure_incident.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --factor-id <factor_id> \
  --frozen-oos-start <YYYY-MM-DD> --frozen-oos-end <YYYY-MM-DD> \
  --frozen-oos-release-token-sha256 <sha256> \
  --exposed-overlap-start <YYYY-MM-DD> --exposed-overlap-end <YYYY-MM-DD> \
  --exposed-row-count <count> --exposed-period-count <count> \
  --source-path <source> --panel-path <panel> \
  --metrics-path <metrics> --runner-path <runner> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id> \
  --incident-at <UTC_ISO8601_Z>
```

若早期流程只留下公开 marker，必须用恢复入口把它补登到 workspace 外的 Host
签名 registry；此动作只补齐永久负面证据，不恢复 OOS authority：

```bash
python3 scripts/register_factorforge_oos_exposure_incident_host_private.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

若原始 runner 字节未冻结，保留现有 incident，不得覆盖；以固定 UTC 时间追加
create-only provenance correction，并在精确重放时复用同一时间：

```bash
python3 scripts/record_factorforge_oos_exposure_provenance_addendum.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --correction-at <UTC_ISO8601_Z>
```

同一 Host pair 必须从 `AUTHORING`、`PREREGISTERED`、`READY` 到 allocation、
release/consume 与 terminal closure 的每个 current-authority 入口显式重放；正式
mutation 必须在同一 live incident guard 中完成祖先检查、写入和 readback。Agent 的
无秘密 structural replay 只能给出 `current_formal_authority_verified=false`。

allocation 同时在 Host trust root 下保存一份签名的私有 carrier locator；公开
allocation、receipt、registry、CLI 输出和 wrapper proof 均不包含 carrier、private
root 或 trust root 路径。进程重启后的 Host finalizer 只接受外部 Host trust pin，
并通过仅注入 finalizer 子进程的
`FACTORFORGE_OOS_HOST_TRUST_ROOT` / `FACTORFORGE_OOS_HOST_INSTALLATION_ID`
解析 locator：

```bash
FACTORFORGE_OOS_HOST_TRUST_ROOT=<host_trust_root> \
FACTORFORGE_OOS_HOST_INSTALLATION_ID=<installation_id> \
python3 scripts/finalize_factorforge_web_factor_proof.py \
  --workspace-root <factor_workspace> \
  --report-id <child_report_id> \
  --expected-host-trust-manifest-sha256 <out_of_band_host_pin> \
  --resolve-host-private-oos
```

secure child 还必须由 Console 仅向 Host finalizer 注入
`FACTORFORGE_EVO_CHILD_CONTAINER_STATE_ROOT` 与
`FACTORFORGE_EVO_CHILD_CONTAINER_JOB_ID`。finalizer 在读取 locator 或发布任何 OOS
字节之前，持有 child container runner lock，验证全局最新且成功的
`validate_step4` Host-signed termination receipt；任何更晚 stage、未 reconcile 的
inflight、仍可 inspect/枚举到的 child container、错误 identity/workspace/trust pin
都固定 token BLOCK。该锁持续持有到 release、consume 与 finalization 全部落盘，之后
runner 看到任一 OOS artifact 也永久拒绝再次启动 Agent stage。公开 release 与
finalization 只绑定 termination receipt 的 opaque id/hash 及 closed authority
projection，不公开 Host-private receipt/state 路径。完成态重放可不再读取 carrier，
但仍必须重验同一 termination receipt 与其 release/finalization binding。

secure child allocation 不允许退回显式 carrier/private-root argv。locator 必须重放
签名、allocation identity、raw/derived/build-authority hash、uid/mode、唯一 inode
和 carrier hash；失败只输出固定 BLOCK token，不得把 Host-private 路径写入 stderr
或公开 wrapper proof。私有完整 panel 只在确定性的 Host-private staging 中生成，
hash 验证通过后才原子发布；同一 staging 的 crash residue 可在 Host finalizer retry
中清理，任何旧式/未知 hidden staging 必须 BLOCK。

正式命令为：

```bash
python3 scripts/approve_factorforge_pre_oos_child.py \
  --workspace-root <factor_workspace> \
  --report-id <parent_report_id> \
  --human-approval-receipt <signed-external-human-receipt.json> \
  --human-trust-manifest-sha256 <out-of-band-manifest-pin> \
  --host-trust-root <host-private-runtime-trust-root> \
  --installation-id <installation_id> \
  --incident-trust-root <host-private-runtime-trust-root> \
  --incident-installation-id <installation_id>
```

Bridge signer 与 incident pair 必须绑定同一 canonical trust-root 路径和同一
installation ID；同一个 live guard 覆盖 lineage 重放、三件语义投影与 ticket
签发/readback。

仓库不提供由 Agent 生成 external-human key/receipt 的 CLI。签名系统和 human
trust pin 必须来自外部控制面。receipt 必须同时绑定 selected law、delta、经济
反投影、child identity 和 Host 预先分配的 fresh sealed OOS。

PASS 会 materialize 三个 closed、可重放的语义投影：pre-OOS human approval、
`handoff_to_step3b` 和 child intent projection；此外 Host 会签发一个 non-ready
authorization ticket，作为后续隔离 authoring/preregistration 的控制面输入。只有当
完整 child preregistration receipt 已经存在并通过严格重放时，bridge 才可另外投影
`MATERIALIZATION_READY` ticket。它不会写 Step5/6 iteration、不会 materialize child
inputs、不会 release OOS、更不会执行 child。child materializer 必须重新 replay 当前
EVO、签名、preregistration 和 fresh-OOS gates。

child materializer 只做验证与受控 materialization，不替 Host 分配数据，也不替
Agent 编写研究语义。调用前，Host 必须已写入并 CAS 登记 child 专属 OOS
allocation；隔离的 Agent authoring session 必须产出 child research state、conjecture、
approach registry、base trial ledger 和 report-scoped Web plan；Host 只做签名 admission、
closed-schema 校验和确定性投影；独立 reviewer 必须签发 truthful child assurance。

生产入口是 Console Host 的 `prepare_evo_child_execution()` 七阶段链，不是直接运行
`materialize_step6_child_revision.py`：

```text
AUTHORING_ADMITTED
  -> CHILD_PREREGISTERED
  -> MATERIALIZATION_READY
  -> CHILD_MATERIALIZED
  -> POST_MATERIALIZATION_ADMITTED
  -> CONTAINER_ADMITTED
  -> CHILD_EXECUTION_READY
```

独立调试 preregistration 的正式 `validate`、`materialize` 与 `validate-receipt`
子命令时，也必须显式给出同一个事故权限上下文；projection 子命令仍是
structural-only：

```bash
python3 scripts/preregister_factorforge_evo_child.py <validate|materialize|validate-receipt> \
  --workspace-root <factor_workspace> \
  --parent-report-id <parent_report_id> \
  --child-report-id <child_report_id> \
  --expected-host-trust-manifest-sha256 <out_of_band_sha256> \
  --incident-trust-root <host-private-incident-trust-root> \
  --incident-installation-id <host-installation-id> \
  <subcommand-specific-control-arguments>
```

该内部 materializer 只允许 Ultimate/loop/Console Host 调用，并必须绑定 out-of-band
`expected_host_trust_manifest_sha256`。直接 CLI 会固定返回
`BLOCKED_DIRECT_MATERIALIZE`；它不是生产操作入口。EVO pre-OOS 路径也不得把 legacy
post-Step6 `--synthesis-path` 当作 child 语义来源。

`orchestrate_factorforge_evo_pre_oos_outcome.py`、
`orchestrate_factorforge_evo_transfer_use.py` 与
`materialize_factorforge_web_evo_is_checkpoint.py` 是 wrapper/Console 调用的
Host-only 内部事务封装，不是与 Ultimate 并列的第二个生产入口。仅在调试这些事务
本身时按各自 `--help` 提供 required trust/installation 与 frozen hash 参数；其 PASS
也不能单独建立 factor verdict。

缺少任一 child control 或 fresh allocation 时，正确结果是
`WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION`，不是自动复制父 OOS。父、祖先或
sibling 的 sealed token、同 snapshot 重叠窗口、已 consumed allocation 均必须
BLOCK。

### 11.5 经验运行面

EVO V2 memory 使用 Host-owned Python runtime API 完成 review projection、独立
review session、actual-use change receipt、Host-private admission 和
mechanism-first retrieval。当前没有允许 Agent 直接 canonical-promote 的 CLI；
没有 runtime completion receipt、独立 reviewer、Host admission 或真实
before/after change 时必须保持 candidate/pending。市场 state/event 字段只保留在
episode 和 diagnostic 中，retrieval score 不读取它们。

### 11.6 Child container、耐久恢复与递归 lineage

正式 child 的 Agent-authored execution 只允许四个 stage 进入签名容器：
`run_step3b`、`validate_step3b`、`run_step4`、`validate_step4`。容器必须
`network=none`，engine/rootfs 只读，只有 child workspace 可写；不得挂载 Host state、
trust、sealed carrier、OOS locator 或数据凭据。Host 在 `validate_step3b` 与 Step4
之间物化并签名 purged-IS prefetch receipt，Agent stage 只能重放该 snapshot，不能重新
访问 Data API。

每个 stage 必须有 Host-signed inflight、container termination 和 process-tree-absent
evidence。`CHILD_RESUME_READY` 只能按签名 checkpoint 恢复 4/5/6；
`CHILD_RECOVERY_READY` 只授权 Host finalizer。若 wrapper proof 仍是 `RUNNING`，只有
Host-signed exact-command recovery admission 才能从已完成命令的下一条恢复；admission
必须绑定 proof snapshot、全局最新 termination、原 inflight、精确下一命令与 prefetch
receipt。未知前缀、漂移 receipt 或仍存活的 process tree 一律 BLOCK。普通 wrapper
`PASS` 或 child execution receipt 都保持 `formal_factor_verdict=NOT_ISSUED`；只有经
正式终态验证的 `EVO_CHILD_TERMINAL_CHECKPOINT` 可以签发 `ACCEPT|REJECT`。

若 Council 选择 `MINIMAL_MECHANISM_DELTA` 并产生 descendant，下一代必须完整重走
external human、fresh allocation、authoring、assurance、preregistration、READY 和
container admission。递归恢复必须逐边重放签名 `HOST_CHILD_HANDOFF` phase receipt，
并持久化 root-to-active lineage；不得只信 Console DB 当前行或复用祖先 OOS/identity。
