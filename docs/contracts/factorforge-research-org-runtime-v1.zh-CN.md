# Factor Forge Research Organization Runtime v1 合同

## 0. 文档状态

本文定义 Research Organization 的 Phase 2 runtime 合同。它建立在：

- `factorforge_research_org_plan_v1`；
- `factorforge_agent_task_v1`；
- `factorforge_agent_result_v1`；
- 每因子独立 factor workspace；

之上。

本合同证明的是 **受 Host 控制的多 session 调度、私有结果 ingress、签名收据、依赖因果绑定与独立 Council runtime**。它不证明某个因子有效，不替代 Step1-6、回测、factor proof 或 production research proof。

实现入口：

```text
factor_factory/research_org/runtime.py
factor_factory/research_org/runtime_ledger.py
factor_factory/research_org/runtime_trust.py
factor_factory/console/container_agent_adapter.py
scripts/run_factorforge_research_org_runtime.py
scripts/validate_factorforge_research_org.py
scripts/run_factorforge_research_org_runtime_smoke.py
```

## 1. Authority

### 1.1 权威状态

Host-private SQLite ledger 是 runtime authority：

```text
<console-state-root>/jobs/<job_id>/research_org_private/
  <runtime_id>/runtime_ledger.sqlite3
```

SQLite 使用：

- WAL；
- `synchronous=FULL`；
- foreign keys；
- `BEGIN IMMEDIATE`；
- task、attempt、receipt、admission 和 event 唯一约束；
- Host 验收时 `mode=ro` 与 `query_only=ON`。

validator 不创建缺失的 private root、ledger 或 trust key。缺失即 BLOCK。

### 1.2 Workspace projection

workspace 中的 JSON 是可重建、可公开审计的 projection，不是 authority：

```text
objects/research_organization/<report_id>/runtime/
  runtime_state.json
  dispatcher_lock.json
  cancel_request.json                         # optional
  events/event_<sequence>.json
  attempts/<role_id>/<attempt_id>/
    context_manifest.json
    attempt.json
    session_receipt.json
```

Host ledger 保存每个 context、attempt 和 receipt projection 的 hash。攻击者即使修改 workspace JSON 并重新计算 JSON content hash，也不能覆盖 private ledger binding。

canonical role result 仍写到冻结 task 的：

```text
objects/research_organization/<report_id>/results/<role_id>.json
```

只有 Host 可以执行 canonical admission。

## 2. Runtime identity

`runtime_id` 由冻结 `plan_sha256` 导出。下列身份必须全链一致：

```text
factor_id
research_id
report_id
job_id
runtime_id
plan_sha256
task_id / task_sha256
role_id
attempt_id / attempt_no
scheduler_epoch
```

一次 attempt 还必须绑定：

- 唯一 `session_uid`；
- 唯一 Host `runtime_handle` 及其 hash；
- 唯一 provider session handle hash；
- 唯一 idempotency key；
- adapter challenge；
- dispatch event sequence；
- 精确 dependency admission snapshot。

Independent Council 的 `parent_session_uid` 必须为 `null`。Council 不得继承作者或 Director session。

## 3. Context isolation

Host 只将 task 声明的文件复制到 attempt-private staged context。Agent 获得：

- staged files 的只读视图；
- 自己的 private output path；
- 不可写的 canonical factor workspace；
- 不可见的 Host ledger、Host admission key、其他 session context 和其他未声明结果。

容器可只读使用 engine source/skills，但 worktree 中的 `factor_research/`、
`knowledge/`、`data/`、`runs/`、`evaluations/`、`generated_code/` 和
`archive/` 会被空目录遮蔽；随后只把当前 role 的 staged context 挂载到
当前 factor workspace 路径。整个 attempt private root 也是只读挂载，只有
`home/`、`agent/` 和 `output/` 三个明确子目录可写，因此不能从备用路径改写
staged context。

context manifest 冻结：

- source relative path；
- SHA-256；
- size；
- dependency admission receipt；
- scheduler epoch；
- idempotency key；
- adapter challenge。

对于有依赖的角色，Host 计算完整传递依赖闭包，不只复制直接 parent。
每个已 admission dependency 的 public `artifact_refs` 也必须在复制前重新校验
workspace-relative path 与 SHA-256，然后进入 staged context。由此 Quant、
pre-execution Validation 和 Independent Council 可以读取 Host Director 绑定的
`identity/web_research_plan.json` 与 public ledger，而不是只看到一句摘要。

本 runtime 的组织角色运行在 `pre_formal_research_design` 阶段：Quant 审计
estimator/implementation boundary，Validation 审计 preregistration/falsification，
Independent Council 审查完整执行前设计。三者均不得声称已有 backtest evidence
或给出 empirical factor verdict；该责任属于后续 Ultimate Step6。

三者的公开输出使用 `factorforge_preformal_design_review_v3` 与固定
design-only `claim_scope`。公开 record 是闭合的 controlled-check 结构：claims
必须逐项等于有序 checks，finding/falsifier 只能使用合同 code，blockers 只能是
被阻断的 check IDs，executive summary 只能使用固定语义。不存在可承载 completed
simulation、realized metric 或 promotion suitability 改写的自由文本字段；旧的
语义扫描仅作为纵深防御。Evidence refs 仍只能引用 frozen task/input、已
admission 的直接/传递 dependency result，或这些 result 已绑定且同时存在于
staged manifest 的 hash-bound artifact；staged 可见性本身不构成 authority。

关闭结构不只覆盖 v3 record 本身。`factorforge_agent_result_v1` 外层 envelope
必须按 task independence class 使用精确字段集，内部 `identity` 也必须与 frozen
task identity 使用相同且仅相同的 keys；Council 的
`independence_attestation` 与 formal verdict、所有 public `artifact_refs`、以及
Data Liaison materialize 后的 canonical request refs 也必须为 exact shape。
任何相邻对象中的额外 verdict、note 或自由文本字段都会在 Host admission 前
BLOCK，不能通过重新计算 content hash 获得合法性。

Host 在 admission 前重新检查 staged context 未变化。Agent 输出不得包含 private chain-of-thought；只允许公开、可复现的定义、关键推导步骤、假设、证据引用、falsifier 和 uncertainty。

## 4. Signed receipts

安装级 trust store 使用两个独立 Ed25519 key：

```text
runtime_adapter
host_admission
```

外部 Host Research Director 的主 Agent receipt 还必须先通过
`factorforge_console_agent_run_v1` 结构与绑定校验。仅验证 receipt 文件位于
`state/jobs/<job_id>` 不足以建立来源：Host 必须逐项核对 job/factor/research/
report identity、agent ID、session-key hash、provider、model、开始/结束时间、
returncode、stdout/stderr tail，并与 adapter 返回的 `AgentRunResult` 完全一致。

trust root 必须为当前用户所有、权限不宽于 `0700`；private key 文件必须为单链接普通文件，权限不宽于 `0600`。validator 只加载既有 key，不自动生成。

### 4.1 Adapter receipt

Adapter receipt 必须签名绑定：

- 完整 runtime/task/role/attempt identity；
- scheduler epoch 与 dispatch event sequence；
- plan、task、context hashes；
- dependency admission snapshot；
- idempotency key 与 adapter challenge；
- session UID、runtime handle hash、provider handle hash；
- adapter installation/build；
- pinned container image digest；
- isolation profile；
- private output hash/size；
- return code、cancel、termination 与 error class。

只有 `sha256:<64 hex>` image digest 可获得 `signed_adapter` evidence class；未 pin image 只能得到 `signed_adapter_unpinned`，不能满足 formal runtime。

### 4.2 Host admission receipt

Host 在同一 SQLite transaction 内：

1. 验证 adapter signature 和全部 binding；
2. 检查 cancel fence；
3. 写 completion event；
4. 对 candidate result 生成 Host admission receipt；
5. 写 admission/event/task/attempt 状态；
6. commit；
7. 再投影 canonical workspace result 和 session receipt。

Host receipt 必须绑定 adapter receipt ID、result hash、dependency snapshot、context hash和 event sequence。合法但属于其他 attempt 的旧 receipt 不可重放。

Research Director 是 Host external session，不由 specialist adapter 派发。它必须生成独立的 authoring record，逐项绑定 task 的全部 dependency result path/hash、validated plan、公开 ledger 和 Host-private Agent receipt。Host 只从该 record 派生 canonical Director synthesis，并用真实 provider/model/session/timestamp 和 receipt hash 导入 ledger；缺任一绑定都 BLOCK。

Data Liaison 的 staged workspace 同样只读。缺口 request 以完整 payload 写入其 Host-private candidate；Host 先验证 consumer/schema/path，再原子物化到 report-local `data_requests/` 并把 candidate 改写为 path/hash ref。若 result validation、ledger commit、cancel fence 或 canonical admission 失败，本轮 Host-created request 必须删除。

Data Liaison 对 Host-attested base market dataset 的 pre-formal `PASS` 也必须经过 canonical validator，而不能只依赖 skill prompt。Validator 重新读取 frozen catalog snapshot，核对 active receipt 所绑定的唯一 catalog hash，并逐项验证 dataset class、S3 URI、字段、覆盖、producer provenance、read-only permission 和固定的 Step3 deferred checks。PIT/no-future 不是任意文本 presence check：Host 只从受控 `factorforge_information_policy_v1` 或已知 producer 的精确 PIT 合同生成结构化 attestation，validator 再按原始 policy 重算并要求完全相等。该路径只允许研究方案设计，不授权 formal execution；派生 state 仍要求完整 QA/read-smoke 或进入 `NEEDS_DATA`。Catalog admission projection 每次签发时直接重验 receipt freshness，不复用 health cache。

## 5. Dependency scheduler

Task 只有在所有冻结 dependency role 已经：

- canonical admission；
- `status=PASS`；
- result hash 与 Host receipt ID 已冻结；
- admission event sequence 早于本 task dispatch event；

时才可派发。

attempt context、adapter receipt 和 Host receipt 都必须携带同一 dependency snapshot。运行后修改 dependency hash、receipt 或 event ordering 会 BLOCK。

## 6. Retry, cancel and recovery

### Retry

- 每次重试使用新的 attempt ID、session UID、runtime handle、provider handle 和 challenge；
- `max_attempts_per_role` 为硬预算；
- isolation/context/secret 等 non-retryable failure 不再重复派发；
- retry disposition 写入 ledger 和 workspace session receipt。

### Cancel

- Host ledger 的 `cancel_seq` 是 admission fence；
- cancel 之后到达的 candidate 不能 canonical admit；
- adapter 只能终止当前 runtime 拥有且 label/handle 匹配的 session；
- 不得按模型名、全局容器列表或模糊进程名取消其他研究任务。

### Crash recovery

若 Host 在 ledger dispatch commit 后、workspace projection 前崩溃：

1. 下次 scheduler 从 ledger 找到 `DISPATCHED` attempt；
2. 只终止该 ledger 持有的 runtime handle；
3. termination 未确认则 BLOCK；
4. 将 attempt 标为 `LOST`；
5. 重建缺失 context/attempt projection；
6. 写 `ABANDONED` receipt 与 recovery event；
7. 仅在仍可重试时创建新 session。

workspace event 已写而 state 尚未更新的窗口由 event-head reconciliation 修复；其他不一致 fail closed。

## 7. Assurance levels

### `workspace_runtime_projection_valid_only`

只验证 workspace state/event/context/attempt/receipt/result projection。它不证明 Host-private ledger 或签名链存在。

### `transactional_runtime_unverified_sessions`

Host-private ledger 与 projection 一致，但 session 使用显式 test/developer runner，或缺少 formal signed/pinned evidence。它不能满足正式独立性。

### `signed_specialist_runtime_complete_host_director_external`

只有以下全部满足才返回：

1. 所有 required tasks `ADMITTED_PASS`；
2. run state 为 `COMPLETE`；
3. 所有 specialist admissions 来自有效 signed adapter receipt；
4. 所有 image digest pinned；
5. 所有 Host admissions 签名且深层 binding 重算通过；
6. 所有 attempts terminal，workspace projection hashes 已绑定；
7. provider/session handle 不复用；
8. dependency event ordering 有效；
9. Independent Council 是独立 session；
10. ledger、event chain、canonical results 和 workspace projection 无差异。

该 assurance 证明 runtime independence，不证明 factor `ACCEPT`。

## 8. CLI

### Run / resume

```bash
python3 scripts/run_factorforge_research_org_runtime.py \
  --workspace-root <factor_workspace> \
  --worktree <pinned_engine_worktree> \
  --state-root <console_state_root>
```

### Cancel

```bash
python3 scripts/run_factorforge_research_org_runtime.py \
  --workspace-root <factor_workspace> \
  --worktree <pinned_engine_worktree> \
  --state-root <console_state_root> \
  --cancel --cancel-reason <reason>
```

### Formal validation

```bash
python3 scripts/validate_factorforge_research_org.py \
  --workspace-root <factor_workspace> \
  --require-runtime-formal \
  --runtime-private-root <job_private_root> \
  --runtime-trust-root <trust_root> \
  --runtime-installation-id <installation_id>
```

### Ultimate binding

```bash
python3 scripts/run_factorforge_ultimate.py ... \
  --research-org-runtime-mode formal-complete \
  --research-org-runtime-private-root <job_private_root> \
  --research-org-runtime-trust-root <trust_root> \
  --research-org-runtime-installation-id <installation_id>
```

Ultimate 的 runtime mode 默认 `off`，不会改变 legacy run。`if-present` 和 `required` 可以只验证 projection；只有 `formal-complete` 允许 Ultimate wrapper 声明 signed runtime independence。

## 9. Blocker classes

主要 blocker：

```text
BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_MISSING
BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_CANCELLED
BLOCK_FACTORFORGE_RESEARCH_ORG_SESSION_FAILED
BLOCK_FACTORFORGE_RESEARCH_ORG_SESSION_RECEIPT_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_PATH_INVALID
```

底层 reasons 必须保留，例如：

```text
dependency_not_admitted_pass
dependency_snapshot_changed
adapter_session_or_receipt_reused
ledger_dependency_binding
ledger_projection_hash
formal_signed_runtime_not_satisfied
private_output_changed_while_reading
unsafe_private_runtime_ledger
```

## 10. 非目标与剩余阶段

本合同尚不实现：

- Data API delivery import/resume；
- attachment/MIME quarantine；
- complete-dispatch directory rename；
- plan revision/CAS/current pointer；
- 自动 patch merge 或 specialist code worktree；
- 将 organization runtime 默认插入 legacy/CLI-only Ultimate runs（production Web 已强制接入）；
- production factor research golden run。

Production Console 已按 intake -> Host Director admission -> Quant/Validation/Council ->
`formal-complete` Ultimate 的顺序执行，并投影 role state、session/receipt count 和
assurance；它不展示 task logs、secrets 或 private chain-of-thought。Plan-only 或
Ultimate-only evidence不能获得 Web `COMPLETED`。

## 11. 验收

```bash
python3 scripts/run_factorforge_research_org_runtime_smoke.py
```

该 smoke 只在 `/tmp` 使用 deterministic signed fake adapter，输出必须包含：

```text
contract_smoke_only=true
production_research_proof=false
FACTORFORGE_RESEARCH_ORG_RUNTIME_SMOKE PASS
```

正式验收还必须通过 focused tests、entrypoint hygiene、`git diff --check` 和独立 reviewer。未运行真实模型/容器/production Step3B/Step4/Step6 时，不得将 contract smoke 描述成 production proof。
