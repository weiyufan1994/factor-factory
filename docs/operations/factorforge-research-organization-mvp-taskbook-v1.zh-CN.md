# Factor Forge Research Organization v1 MVP 任务说明书

## 0. 文档状态

本文是已完成的 **Phase 1 planning MVP** 施工与验收说明，保留用于审计最初范围，不再代表 Research Organization 的全部当前能力。Phase 2 runtime 的当前权威合同是：

```text
docs/contracts/factorforge-research-org-runtime-v1.zh-CN.md
```

Phase 1 的目标是建立 **deterministic organization planning、workspace-local contracts、validation gate 和只读 UI projection**。

当前 MVP 不是：

- 自动多 Agent execution；
- 完整 Research Director orchestration；
- persisted state machine；
- independent Council run；
- production factor research proof。

下列“不是/非目标”条目只描述 Phase 1 当时的验收边界。真实 session、Host-private ledger、signed receipt、dependency scheduler、retry/cancel/recovery 已在 Phase 2 实现；dispatch directory staging、Data resume 和完整 Ultimate 自动推进仍未实现。

权威文档：

```text
docs/architecture/factorforge-research-organization-v1.zh-CN.md
docs/contracts/factorforge-research-org-plan-v1.zh-CN.md
docs/contracts/factorforge-agent-task-result-v1.zh-CN.md
```

## 1. MVP 目标

当前施工必须实现：

1. 一个因子对应一个顶层用户任务和一个隔离 factor workspace；
2. Host 在 `identity/research_organization_plan.json` 冻结唯一 organization plan；
3. deterministic router 优先读取 economic/research text，并将公式/代码作为低权重输入；
4. plan 内嵌 versioned role registry；
5. 为 required roles 生成 task files 和 dispatch manifest；
6. task/result/data request 路径限定在当前 report 的 organization object root；
7. `factorforge_agent_result_v1` 作为统一 outer envelope；
8. 领域 `factorforge_domain_research_proposal_v1` 放在 outer `public_research_record`；
9. Ultimate/workspace validator 可以选择性或强制验证 frozen plan；
10. Console 可以展示 route/role plan，但必须明确仅为 dispatch contract、independence 尚未满足；
11. no silent `single_agent_fallback`；
12. 所有当前能力有 positive/negative test 或 smoke。
13. Host 可以验证并原子 admit 单个私有候选 result，collection 自动阻断 isolated/independent session reuse。

## 2. 非目标与禁止扩张

本轮不要求、也不得声称已经实现：

- 创建 Codex/OpenClaw specialist sessions；
- 并行 dispatch、wait、retry、cancel；
- task status 从 PENDING 自动推进（当前仅在 admission 时动态检查依赖，不持久化推进）；
- runtime-to-Host private transport、session receipt 和 secret scan；
- dispatch/result staging directory 和整目录 rename；
- CAS state revision 或 `events.jsonl`；
- plan revisions、`current.json`、supersedes chain；
- blind-context 的 runtime proof；
- Director synthesis 或 measurement program freeze；
- Data delivery import/resume；
- Agent 自动代码 worktree 分配/merge；
- production Step3B/Step4/Step6、worker 或 clean-data mutation；
- formal factor promotion proof。

也不得：

- 新增 workspace 顶层 `org/` required dirs；
- 修改 shared Data API canonical data；
- 写 repo-root `knowledge/` 或 generated `data/`；
- 用一个 authoring Agent 冒充多个 independent roles；
- 将 private chain-of-thought 写入 workspace/UI；
- 使用 `git add .`；
- 自动 commit/push/merge。

## 3. 当前 Artifact 合同

```text
<factor_workspace>/
  identity/
    research_organization_plan.json
  objects/
    research_organization/
      <report_id>/
        inputs/
        dispatch_manifest.json
        tasks/
        results/
        data_requests/
```

硬边界：

- plan 固定在 `identity/`；
- organization object root 固定为 `objects/research_organization/<report_id>/`；
- dispatch/tasks/results/data_requests 不得逃出该 root；
- workspace initializer 不增加顶层 `org/`；
- 所有 path 必须 workspace-relative，禁止 absolute、`..` 和 symlink escape。

## 4. 当前代码范围

### 4.1 新增 deterministic core

```text
factor_factory/research_org/
  __init__.py
  contracts.py
  director.py
  registry.py
  router.py
```

职责：

- `contracts.py`：contract constants、blockers、stable JSON hash、workspace path guard、single-file atomic replacement、private reasoning scan；
- `registry.py`：deterministic embedded role registry；
- `router.py`：weighted deterministic domain routing；
- `director.py`：plan/task/dispatch builder、bundle writer/validator、result validator、Ultimate gate；
- `__init__.py`：公开 API。

### 4.2 新增 CLI

当前脚本名称必须精确为：

```text
scripts/build_factorforge_research_org_plan.py
scripts/validate_factorforge_research_org.py
scripts/run_factorforge_research_org_smoke.py
```

### 4.3 当前集成点

```text
scripts/run_factorforge_ultimate.py
scripts/validate_factor_research_workspace.py
scripts/run_factor_research_workspace_smoke.py
factor_factory/console/agent_adapter.py
factor_factory/console/run_service.py
factor_factory/console/web_ui.py
tests/test_factorforge_console_research_workbench.py
```

集成边界：

- Ultimate 只验证/暴露 plan，不调度内部 specialist agents；
- workspace validator 可要求 organization bundle；
- Console run service 生成/保留 bundle，并将 frozen plan 提供给初始 authoring Agent；
- authoring Agent 明确不能冒充 specialist roles 或 independent Council；
- Console “研究团队”只展示 plan projection，不能展示角色已运行；
- Console assurance 必须保持 `routing_and_dispatch_contract_only`，`independence_satisfied=false`。

### 4.4 当前测试

```text
tests/test_factorforge_research_organization.py
tests/test_factorforge_console_research_workbench.py
scripts/run_factorforge_research_org_smoke.py
scripts/run_factor_research_workspace_smoke.py
```

## 5. 工作包 RO-MVP-01：Contracts 与安全 helper

### 实现

定义并导出：

```text
factorforge_research_org_plan_v1
factorforge_agent_registry_v1
factorforge_agent_task_v1
factorforge_agent_result_v1
factorforge_domain_research_proposal_v1
factorforge_role_research_record_v1
factorforge_research_org_dispatch_v1
```

实现：

- stable JSON SHA-256；
- content hash 排除自身 hash 字段；
- safe ID；
- workspace-relative path normalization；
- ordinary-file/symlink guard；
- builder artifact 使用 temp file + `os.replace()` 单文件写入；
- canonical result 在 frozen plan 文件锁下使用 temp file + atomic hard-link create，目标存在即不覆盖；
- recursive private reasoning key detection。

### 验收

- 相同 payload hash 稳定；
- tampered hash 被阻断；
- absolute/`..`/symlink path 被阻断；
- private reasoning key 在任意嵌套层被阻断；
- 文档不得把单文件 replace/create 称为 staging-directory atomic publish。

## 6. 工作包 RO-MVP-02：Deterministic Router

### 实现

合同：

```text
factorforge_research_domain_route_v1
```

输入来源及权重：

| Source | Weight |
|---|---:|
| hypothesis | 4.0 |
| title | 3.0 |
| research_direction / decision | 3.0 |
| report | 2.5 |
| formula / code | 1.0 |

Active domains：

```text
fundamental
price_volume
```

Planned domains：

```text
event_text
macro_cross_asset
```

Route states：

```text
ROUTED
ROUTED_WITH_CAPABILITY_GAP
UNDER_SPECIFIED
WAITING_CAPABILITY
```

### 验收

1. DCF/free-cash-flow hypothesis 即使附带 `CLOSE/VOLUME` formula，Fundamental 仍可优先；
2. intraday price-volume hypothesis 路由到 Price-Volume；
3. fundamental + price-volume 混合文本产生 lead/supporting route；
4. event lead 在当前 registry 下进入 `WAITING_CAPABILITY`；
5. 无可识别信息进入 `UNDER_SPECIFIED`；
6. routing payload 保留 input hash、scores、public evidence 和 capability gaps；
7. 验收只称其为 deterministic heuristic，不称为 deep semantic Director Agent。

## 7. 工作包 RO-MVP-03：Embedded Role Registry

### 实现

Active roles：

```text
research_director
fundamental_researcher
price_volume_researcher
knowledge_librarian
data_liaison
quant_implementation
validation_evidence
independent_council
```

Planned roles：

```text
event_researcher
macro_cross_asset_researcher
```

每个 role 必须有：

- status/capability/activation；
- skills/input/output contract；
- read/write scopes；
- model policy；
- independence class/session requirement；
- allowed tools/forbidden side effects。

Registry snapshot 内嵌于 plan，合同名必须为：

```text
factorforge_agent_registry_v1
```

### 验收

- registry build deterministic；
- required active roles 全部存在；
- duplicate/invalid role 被阻断；
- required role 不能引用 planned/retired role；
- `isolated_session`/`independent_session` 只解释为当前政策，不作为 session receipt。

## 8. 工作包 RO-MVP-04：Plan、Task 与 Dispatch Builder

### 实现

Builder 必须：

1. 验证 workspace manifest；
2. 绑定 `factor_id/research_id/report_id/job_id`；
3. 生成 route、embedded registry 和 role plan；
4. 写 frozen plan；
5. 捕获已有 request/authoring/knowledge/catalog input snapshots；
6. 为 required role 生成 task；
7. 生成 dispatch manifest；
8. 写完后重新验证 bundle。

Task dependency：

```text
quant_implementation <- domain/intake roles
validation_evidence <- quant_implementation
independent_council <- validation_evidence + research_director
```

### 冻结规则

- plan 不存在：允许 build；
- plan 已存在、未传 `--preserve-existing`：BLOCK；
- plan 已存在、传 `--preserve-existing`：验证并保留；
- preserve 时 identity 不一致：BLOCK；
- 不实现 revision/current pointer/supersedes。

### 验收

- plan 路径和 organization root 精确；
- input/task/dispatch/result refs 均为 workspace-relative；
- task role snapshot 与 plan registry 一致；
- expected result 必须在 task write scope；
- dispatch task SHA 与文件一致；
- plan preservation byte-stable；
- builder 不生成虚构 Agent result。

## 9. 工作包 RO-MVP-05：Result Envelope Validator

### 实现

统一 outer envelope：

```text
factorforge_agent_result_v1
```

Allowed status：

```text
PASS
BLOCK
NEEDS_DATA
NEEDS_CLARIFICATION
```

Allowed producer mode：

```text
real_agent
single_agent_fallback
```

Domain/Data Liaison inner plugin：

```text
factorforge_agent_result_v1.public_research_record
  contract_version = factorforge_domain_research_proposal_v1
```

Other role inner plugin：

```text
factorforge_agent_result_v1.public_research_record
  contract_version = factorforge_role_research_record_v1
```

### 验收

- task/identity/role/content hash binding；
- plan-frozen input refs 与 task input artifacts 完全一致；
- deterministic dispatch order/task ID 不可通过重签替换；
- controlled input/task/result directories 不接受未绑定文件或 symlink；
- inner contract 等于 task `output_contract`；
- normal domain、Data Liaison 和 role record 的最低字段集；
- artifact path/hash；
- private reasoning recursive block；
- Council real-agent attestation；
- fallback Council `independence_satisfied=false`；
- fallback 不得写 `formal_independent_verdict`；
- direct validator 在传入 peer session IDs 时阻断 reuse；
- bundle validator 自动完成 collection-level peer session audit；
- Host admission 在 plan 文件锁内对候选与既有结果做双向 session 隔离检查，提交顺序不能绕过。

## 10. 工作包 RO-MVP-06：Data 组外部合同

### 实现

Plan 固定：

```json
{
  "mode": "external_contract_only",
  "data_liaison_may_materialize_data": false,
  "request_contract": "data_request_v1",
  "accepted_delivery_evidence": ["catalog_entry", "qa_summary", "delivery_receipt"],
  "missing_data_state": "WAITING_DATA"
}
```

Data Liaison write scope：

```text
objects/research_organization/<report_id>/results/data_liaison.json
objects/research_organization/<report_id>/data_requests/**
```

### 验收

- Data Liaison 不得 materialize data、mutate catalog 或写 shared data；
- missing data 形成 `data_request_v1` 合同边界；
- `WAITING_DATA` 在 workflow policy 中为 nonterminal；
- 当前不验收 delivery import/resume。

## 11. 工作包 RO-MVP-07：Ultimate 与 Workspace Gate

### 11.1 Ultimate CLI

新增：

```text
--research-org-mode off|auto|required
--research-org-plan <path>
```

语义：

- `off`：禁用 gate，且不得同时传 explicit plan；
- `auto`：plan 缺失时兼容 legacy，存在时验证；
- `required`：workspace/plan 缺失或无效时 fail closed；
- explicit path 必须精确等于 `<workspace>/identity/research_organization_plan.json`；
- validated plan state 必须为 `ROUTED`；
- validated plan 路径传入 child env `FACTORFORGE_RESEARCH_ORG_PLAN`；
- Ultimate proof/summary 记录 research organization validation summary；
- `formal_org_independence` 当前始终为 `false`。

### 11.2 Workspace Validator

新增：

```text
--require-research-org
```

语义：

- 显式要求时必须验证 bundle；
- plan 已存在时即使未显式要求，也验证 bundle；
- plan 不存在且未要求时保持 legacy compatibility。

### 验收

- required + missing plan BLOCK；
- valid plan PASS；
- explicit path escape/mismatch BLOCK；
- auto legacy 不伪造 organization assurance；
- dry-run 同样执行 gate；
- gate 不启动 specialist Agent。

## 12. 工作包 RO-MVP-08：Console Projection

### 实现

Console run service：

- 新研究创建 organization bundle；
- trusted resume 使用 `--preserve-existing` 保留 frozen plan；
- 将 plan 文件加入初始 authoring Agent 的只读 packet；
- authoring prompt 明确该 session 不是全部 specialist roles 或 independent Council；
- 正式材料化后验证 bundle并投影 organization summary。

UI “研究团队”只展示：

```text
state
lead_domain
supporting_domains
required_roles
deferred_roles
capability_gaps
dispatch_task_count
validated_result_count
independence_satisfied
```

当前固定 assurance：

```text
execution_state = dispatch_contract_generated
independence_satisfied = false
assurance = routing_and_dispatch_contract_only
```

### 验收

- UI 用“已规划”“待前置条件”，不用“已运行”“已完成”；
- independence 显示“尚未满足”；
- panel 不展示 private CoT；
- UI task/result count 来自 validated bundle；
- Console projection 不等于真实 runtime proof。

## 13. 工作包 RO-MVP-09：CLI 与 Smoke

### Build

```bash
python3 scripts/build_factorforge_research_org_plan.py \
  --workspace-root <factor_workspace> \
  [--request <request.json>] \
  [--preserve-existing]
```

### Validate

```bash
python3 scripts/validate_factorforge_research_org.py \
  --workspace-root <factor_workspace> \
  [--require-results]
```

### Smoke

```bash
python3 scripts/run_factorforge_research_org_smoke.py
```

Smoke 必须覆盖：

- bundle build；
- bundle validate；
- fundamental lead + price-volume support route；
- `single_agent_fallback=false`；
- Host canonical merge policy；
- preserve existing；
- path escape BLOCK。

Smoke 不启动 production research、worker、formal Step3B/Step4/Step6 或真实 specialist Agent。

## 14. Blocker Tokens

当前实现必须使用：

```text
BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_MISSING
BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_IDENTITY_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_PATH_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_REGISTRY_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_ROUTE_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_TASK_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_RESULT_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_INDEPENDENCE_INVALID
```

不得将底层 result/task/route 原因压缩成无法审计的泛化错误。

## 15. 验证命令

在实现 worktree 运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m py_compile \
  factor_factory/research_org/*.py \
  scripts/build_factorforge_research_org_plan.py \
  scripts/validate_factorforge_research_org.py \
  scripts/run_factorforge_research_org_smoke.py

PYTHONDONTWRITEBYTECODE=1 pytest -q \
  tests/test_factorforge_research_organization.py \
  tests/test_factorforge_console_research_workbench.py

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  scripts/run_factorforge_research_org_smoke.py

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  scripts/run_factor_research_workspace_smoke.py

git diff --check
git status --short --branch
```

若 broader console/workspace tests 太慢，可在 reviewer packet 中分别报告 targeted 与 broader 结果；不得把未运行写成 PASS。

## 16. Negative Tests

至少覆盖：

1. missing plan in required mode；
2. request/workspace identity mismatch；
3. plan/task/dispatch/result hash tampering；
4. workspace path escape；
5. inactive required role；
6. input snapshot missing/hash mismatch；
7. result task/identity/role mismatch；
8. private reasoning key；
9. fallback Council overclaim；
10. explicit plan path mismatch；
11. planned domain capability gap；
12. under-specified request；
13. Console independence false projection。

## 17. Reviewer Packet

交付必须列出：

- branch/worktree/base HEAD/current HEAD；
- changed files；
- exact script names；
- artifact layout；
- contract versions；
- verification commands、rc 和关键 token；
- `git diff --check`；
- `git status --short`；
- production boundary；
- 未实现能力清单。

Reviewer 必须明确区分：

```text
organization contract PASS
runtime execution proof
independent Council proof
factor research ACCEPT
production promotion
```

前者不能替代后四者。

## 18. 当前 MVP 完成定义

只有以下全部满足，当前 MVP 才可接受：

1. plan 固定为 `identity/research_organization_plan.json`；
2. 不新增 workspace 顶层 `org/` required dirs；
3. organization object 全部位于 `objects/research_organization/<report_id>/`；
4. deterministic router/registry/role plan 可验证；
5. task/dispatch/input hash 和 workspace scope 可验证；
6. outer result envelope 与 domain plugin nesting 正确；
7. no silent fallback，false Council independence 被阻断；
8. Ultimate required/auto/off gate 语义正确；
9. workspace validator 能按需 require bundle；
10. Console 只按已验证 bundle/result 展示 assurance，不冒充 runtime receipt；
11. targeted tests、smokes 和 diff check 通过；
12. 未启动 production research、worker、正式 Step3B/Step4/Step6 或 clean data mutation；
13. 文档没有把 CAS/events/staging directory/real sessions 写成当前能力或验收项；
14. Host 单结果 admission、immutable conflict 和 collection session uniqueness 有正负例。

## 19. Phase 1 收口时的 Future Backlog（历史记录）

Phase 1 收口时记录的 backlog 如下。第 1、2、3、5、7、11 项已由 Phase 2 runtime 部分或全部关闭；当前权威状态以 runtime 合同和架构书为准。

1. Real runtime adapter 与 Agent session ownership receipt；
2. Dependency scheduler、parallel dispatch、retry/cancel；
3. runtime private transport、signed session receipt 与 secret scanning；
4. Complete-dispatch staging-directory publication；
5. Persisted state、CAS revision 和 events ledger；
6. Plan revision/current pointer/supersedes；
7. Collection-level blindness runtime proof；
8. Director synthesis 与 mechanism freeze；
9. Data delivery import/resume；
10. Ultimate Step1-6 organization state advancement；
11. Console runtime status、attempt/history 和 Council proof projection；
12. Production factor research golden runs。

这份历史 backlog 不计入 Phase 1 MVP done，也不能单凭文档存在证明代码已经实现；每一项仍以代码、validator、测试和独立 review 为准。

## 20. Phase 3 Web Runtime Closure

Phase 3 将 signed organization runtime 接入 production Web 主链，验收顺序固定为：

1. mechanism-bearing evidence 才能激活 domain；formula/code/title 只形成 exploratory candidates；
2. signed Knowledge/Data/Domain intake 先于 Host authoring；
3. Host Director 必须读取 admitted public records，authoring preflight PASS 后以真实 session ID admission；
4. Quant、pre-execution Validation 和 Independent Council 使用传递依赖的 staged context，且 Host plan/ledger artifact refs 必须逐文件 hash 绑定；
5. organization runtime 必须 `COMPLETE` 且 `formal_independence_verified=true`；
6. production Ultimate 必须携带 `--research-org-runtime-mode formal-complete`；
7. Ultimate terminal report 不能绕过 organization gate；Web `COMPLETED` 同时要求组织证明和正常 Step3-6 终态证据；
8. organization Council 只审计执行前研究设计，不得冒充 Step6 empirical Council；
9. Web plan 必须冻结 IS/OOS、purge/embargo、trial budget、multiple testing、timing、cost/capacity model、终态条件、消融和 falsifier；
10. external formula source semantics 必须带 specific source evidence 或 explicit user research override provenance，并明确 source meaning 是否真的 verified；
11. `NEEDS_CLARIFICATION` 保持 `factor_verdict=UNKNOWN`，不运行 Host authoring、materializer 或 Ultimate；
12. production adapter 缺少 specialist runtime 时直接 BLOCK，不允许 plan-only 降级。
13. pre-formal Quant/Validation/Council 只接受 v3 controlled-check record；任何自由文本 claim/finding/falsifier/blocker 或额外 record 字段均 BLOCK。
14. 描述性字段清单不得激活 domain；含关系谓词从句、经济对象和可证伪目标的完整研报机制陈述必须正常路由，关键词共现不得冒充机制。
15. result outer envelope、authority-bearing identity、Council attestation/formal verdict、artifact refs 与 canonical data-request refs 必须 exact-shape；相邻字段不能成为 pre-formal verdict 的自由文本旁路。

Phase 3 仍不实现：同任务 plan revision/current pointer、Data delivery automatic resume、attachment quarantine、complete-dispatch directory rename 和 production factor golden-run acceptance。它们不能被本轮代码/合同 closure 冒充。
