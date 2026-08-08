# Factor Forge Research Organization v1 架构书

## 0. 文档状态

本文同时描述：

1. **当前已实现 MVP**：Research Organization 的计划、路由、角色注册、task/dispatch artifact 和结果 envelope 校验；
2. **目标架构**：后续由 Ultimate/Host 自动运行多个隔离 Agent session，并接入完整状态机、结果 ingress、Data 组和 Council。

除标有“Future Phase”的章节外，本文的 MVP 描述与当前实现对齐。当前实现入口为：

```text
factor_factory/research_org/
scripts/build_factorforge_research_org_plan.py
scripts/admit_factorforge_agent_result.py
scripts/validate_factorforge_research_org.py
scripts/run_factorforge_research_org_smoke.py
tests/test_factorforge_research_organization.py

# thin integration gates/projection
scripts/run_factorforge_ultimate.py
scripts/validate_factor_research_workspace.py
factor_factory/console/run_service.py
factor_factory/console/web_ui.py
```

当前 MVP 是 **planning and validation proof**，不是自动多 Agent 执行 proof，也不是 production factor research proof。

## 1. 不变的组织原则

- 一个因子研究仍对应一个顶层用户任务和一个 `factor_research/<factor_id>/<research_id>/` workspace。
- 用户不需要手工创建 Fundamental、Price-Volume、Knowledge、Data 或 Council 等多个顶层 thread。
- Ultimate 的目标角色是 Research Director；专业研究应由内部独立 Agent session 承担。
- Data 组保持外部独立 thread/repo，通过 `data_request_v1`、catalog、QA 和 delivery receipt 协作。
- Skill 是角色能力和 SOP，不等于 Agent。Agent 还需要独立 session、task packet、工具权限和结果合同。
- 数学工具由 economic hypothesis 和 estimand 选择。Fundamental 不强制 DCF，Price-Volume 不强制随机过程，任何研究都不强制量纲分析。
- Knowledge 只能提供 `advisory_prior`、`counterexample` 和 `tool_candidate`，不能替代当前数学推导。
- Organization 的 `PASS` 只表示组织合同有效，不能替代 protocol、factor、Council 或 proof verdict。

## 2. 当前 MVP 的准确边界

### 2.1 已实现

当前代码可以：

1. 读取并验证已有 factor workspace manifest；
2. 从研究 request 生成冻结的 `factorforge_research_org_plan_v1`；
3. 将 Agent Registry snapshot 内嵌在 plan 中；
4. 用 deterministic weighted router 选择 Fundamental、Price-Volume 或记录 capability gap；
5. 生成 role task files 和 `factorforge_research_org_dispatch_v1` manifest；
6. 对 plan、registry、task、dispatch 和可选 result 做 content hash 与 workspace path 校验；
7. 校验 `factorforge_agent_result_v1` 外层 envelope；
8. 校验领域插件 `factorforge_domain_research_proposal_v1` 位于 envelope 的 `public_research_record`；
9. 递归阻断 private chain-of-thought 字段；
10. 阻断 independent Council fallback 冒充独立 verdict；
11. 用 `--preserve-existing` 验证并保留已有冻结 plan，不覆盖它；
12. 将 Data Liaison 的写入范围限定到当前 report 的 result 和 `data_requests/`；
13. 通过 Ultimate 的 `off/auto/required` gate 和 workspace validator 校验 frozen bundle；
14. 由 Console 创建/保留 bundle，并展示 route、planned roles、task/result count 和明确未满足的 independence。
15. 由 Host 从私有候选 JSON 校验并原子 admit 单个 role result，已落盘结果保持 immutable/idempotent；
16. bundle validator 汇总已存在 result 的 peer session IDs，阻断 isolated/independent role 会话复用。
17. Independent Council task 冻结完整 `required_review_role_ids`，Council attestation 缺少任一当前角色都会 BLOCK。
18. Plan hash 冻结 captured input refs；task 必须精确继承，dispatch/task ID 与 role 顺序由 validator 重算。
19. `inputs/`、`tasks/` 与 `results/` 受目录闭包检查；Data Liaison result 还必须完整绑定其 `data_requests/` 文件集合。未绑定文件、symlink 或目录项会 BLOCK。

### 2.2 当前未实现

以下能力只属于 Future Phases，不能作为当前 MVP 的既成事实或验收项：

- 自动创建 Codex/OpenClaw subagent session；
- 自动并行 dispatch、wait、retry、cancel 或 session receipt；
- 自动 Agent runtime 到 Host 私有候选文件的安全传输、receipt 和 secret scan；
- dispatch 级 staging directory 与整目录 atomic rename；
- runtime receipt 真实性和 blind-context 的外部证明；
- 独立的 organization state 文件、CAS revision 或 append-only events ledger；
- plan revision chain、`current.json` pointer 或 supersedes chain；
- 自动 Director synthesis 和 measurement program freeze；
- Ultimate Step1-6 的自动状态推进；
- Data delivery resume；
- Console 中由真实 session receipt 驱动的 role 运行/完成状态、attempt/history 和 Council proof；
- 自动代码 worktree 分配、patch merge 或 production research。

Builder 的 `write_workspace_json()` 使用临时文件加 `os.replace()` 做**单文件写入替换**。Result admission 在冻结 plan 的跨进程文件锁下完成全 bundle 校验、session 冲突检查和同目录原子 hard-link create，目标已存在时不覆盖。这仍不等于 dispatch 结果目录的 staging/atomic publication。

当前 Console 已有基础“研究团队”投影。没有完整且通过校验的结果集合时，其 assurance 为
`routing_and_dispatch_contract_only`，且 `independence_satisfied=false`；它不是多 Agent execution proof。

## 3. 当前 Artifact 布局

MVP 不新增 workspace 顶层 `org/`，也不修改 `REQUIRED_WORKSPACE_DIRS`。所有新增 artifact 复用现有 `identity/` 和 `objects/`：

```text
factor_research/<factor_id>/<research_id>/
  manifest.json
  identity/
    web_research_request.json
    web_research_authoring_contract.json            # optional input
    factor_knowledge_summary.json                    # optional input
    data_catalog_summary.json                        # optional input
    research_organization_plan.json                  # Host frozen plan
  objects/
    research_organization/
      <report_id>/
        inputs/
          <captured-input>.json
        dispatch_manifest.json
        tasks/
          task_<nn>_<role_id>.json
        results/
          <role_id>.json
        data_requests/
          <request>.json
```

路径含义：

- `identity/research_organization_plan.json` 是当前唯一冻结计划路径；
- registry snapshot 直接嵌入 plan，不另写 registry 文件；
- dispatch/task/result/data request 位于 `objects/research_organization/<report_id>/`；
- `results/<role_id>.json` 是 task 中声明的预期结果路径；
- 当前 builder 写 plan、tasks 和 dispatch，不生成 Agent result；
- Host 用 `scripts/admit_factorforge_agent_result.py` 校验私有候选并原子写入冻结的 expected result path；
- 所有路径必须是当前 workspace 下的相对路径，禁止 absolute path、`..` 和 symlink escape。

## 4. 当前组件

### 4.1 Research Director Bundle Builder

`factor_factory/research_org/director.py` 负责：

- 绑定 workspace identity；
- 调用 router；
- 嵌入 registry snapshot；
- 计算 required/deferred/unavailable roles；
- 生成 plan、task 和 dispatch payload；
- 写入固定路径；
- 验证已有 bundle 和可选 Agent results。

MVP 中的 `generated_by=factorforge_host_research_director` 表示 artifact 所有权，不表示当前已有自治 Director Agent 在后台运行。

### 4.2 Deterministic Domain Router

Router 合同为 `factorforge_research_domain_route_v1`。它对以下来源加权：

| Source | Weight |
|---|---:|
| `hypothesis` | 4.0 |
| `title` | 3.0 |
| `research_direction` / `decision` | 3.0 |
| `report` | 2.5 |
| `formula` / `code` | 1.0 |

因此 economic/research text 优先于公式和代码，但当前 router 仍是透明的 deterministic term-scoring heuristic，不是已实现的深层经济语义 Agent。

当前 active domains：

- `fundamental`
- `price_volume`

已登记但尚未 active：

- `event_text`
- `macro_cross_asset`

Event/Macro 成为 lead 时进入 `WAITING_CAPABILITY`；输入无法识别时进入 `UNDER_SPECIFIED`。

### 4.3 Embedded Agent Registry

Registry 合同版本为 `factorforge_agent_registry_v1`。当前 active roles：

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

`event_researcher` 和 `macro_cross_asset_researcher` 为 `planned`。

每个 role 定义 capability、activation、required skills、input/output contracts、read/write scopes、model policy、independence class、session requirement、allowed tools 和 forbidden side effects。

Registry 中的 `isolated_session`/`independent_session` 是后续 runtime 必须执行的政策；当前 builder 只冻结要求，不创建 session。

### 4.4 Task/Dispatch Artifacts

每个 active required role 生成一个 `factorforge_agent_task_v1`。Task 根据依赖标记为：

- `READY`：当前没有依赖；
- `PENDING`：等待依赖角色结果。

当前代码不会持久化地把 `PENDING` 推进为 `READY`，也没有 scheduler；但 Host admission 会在锁内要求 `depends_on_roles` 的结果均已存在且为 `PASS`，否则拒绝提前落盘。因此早到的 Council 结果不能在事后补齐前序结果后伪装成有效闭环。

`factorforge_research_org_dispatch_v1` 保存 task path/hash、role、phase、status 和 expected result path。它是可验证的 dispatch **manifest**，不是实际 session 已 dispatch 的 receipt。

### 4.5 Ultimate / Workspace Validation Gate

Ultimate 当前支持：

```text
--research-org-mode off|auto|required
--research-org-plan <path>
```

- `auto` 在 plan 不存在时兼容 legacy，存在时验证；
- `required` 在 workspace/plan 缺失或无效时 fail closed；
- explicit plan 必须精确等于 active workspace 的 Host-owned plan path；
- validated plan 必须处于 `ROUTED`；
- gate 输出明确 `formal_org_independence=false` 和 `assurance=routing_and_dispatch_contract_only`。

Workspace validator 支持 `--require-research-org`；plan 已存在时也会验证 bundle。两者都只执行 validation gate，不 dispatch specialist Agent。

### 4.6 Console 基础投影

Console run service 当前会：

- 新研究生成 organization bundle；
- trusted resume 通过 `--preserve-existing` 保留 frozen plan；
- 将 plan 加入初始 authoring Agent 的只读 packet；
- 明确该 authoring session 不能冒充 specialist roles 或 independent Council；
- 在公开 result 中投影 route、required/deferred roles、capability gaps 和 task/result count。

UI 使用“已规划”“待前置条件”和“独立性尚未满足”。它不表示 role session 已创建、已运行或已完成。

## 5. 角色组织

| Role | 当前 MVP | 目标责任 |
|---|---|---|
| `research_director` | active registry/task | 路由、合成、正式阶段协调 |
| `fundamental_researcher` | active registry/task + domain proposal contract | 基本面机制建模；工具开放选择 |
| `price_volume_researcher` | active registry/task + domain proposal contract | 量价/市场结构机制建模；工具开放选择 |
| `knowledge_librarian` | active registry/task | 检索 prior/counterexample/tool candidate |
| `data_liaison` | active registry/task + data request scope | catalog-first 解析；不得 materialize data |
| `quant_implementation` | active registry/PENDING task | 将 frozen mechanism 实现为 operator/direct code/hybrid |
| `validation_evidence` | active registry/PENDING task | 验证实现和正式 evidence |
| `independent_council` | active registry/PENDING task + independence checks | 独立反证；不得由 fallback 冒充 |
| Event/Macro | planned | Future domain plugins |

当前存在 registry/task 不代表该角色已运行、已完成或已产生研究结论。

## 6. Data 组边界

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

Data Liaison 可写：

```text
objects/research_organization/<report_id>/results/data_liaison.json
objects/research_organization/<report_id>/data_requests/**
```

当前 MVP 只冻结接口和路径权限；尚未实现 Data 组 delivery import/resume。Data Liaison 不能修改 catalog、materialize datamart 或写 shared data。

## 7. Result Envelope

`factorforge_agent_result_v1` 是所有角色结果的外层 envelope。领域 Agent 的插件对象必须位于：

```text
factorforge_agent_result_v1.public_research_record
```

且其：

```text
public_research_record.contract_version
  = factorforge_domain_research_proposal_v1
```

领域 proposal 内部还可有一个同名 `public_research_record` 字段，用于公开推导摘要；二者层级不同：

```text
outer result envelope
  public_research_record                 # domain proposal plugin
    contract_version
    public_research_record               # plugin 内公开推导记录
      public_derivation_summary
```

非领域角色使用 `factorforge_role_research_record_v1` 作为 envelope 内部 payload。

当前 validator 会检查 contract version、content hash、task/identity/role binding、result status、producer mode、session ID、插件最低字段、artifact path/hash、private reasoning key，并在 collection 中检查隔离会话复用。当前尚未实现完整 JSON Schema unknown-field closure、Host runtime receipt 真实性或 blind-context 的运行时证明。

## 8. `single_agent_fallback`

当前 plan 固定：

```text
execution_policy.single_agent_fallback=false
```

这意味着 builder 不会静默把组织计划降级为单 Agent，而且当前所有 task 的 `single_agent_fallback_allowed=false`；任何当前 result 使用 fallback mode 都会 BLOCK。未来若某一版本在 frozen task 中显式开放 fallback，对 `independent_council` 仍至少要求：

- 必须有 independence attestation；
- fallback 必须声明 `independence_satisfied=false`；
- 不能提供 `formal_independent_verdict`。

当前 MVP 没有自动 fallback 调度器，也不据此计算正式 proof eligibility。

## 9. 当前安全与验证

已经实现：

- workspace manifest/identity 验证；
- safe ID；
- workspace-relative path、absolute/`..`/symlink 防护；
- plan/registry/task/dispatch/result content SHA-256；
- input artifact 和 result artifact path/hash；
- builder per-file temporary write + `os.replace()`；
- result admission plan lock、双向 session 冲突检查与 atomic no-overwrite create；
- existing plan preservation；
- private reasoning key recursive scan；
- Council fallback overclaim、bundle peer session audit 和 admission prospective session reuse 检查。

尚未实现：

- dispatch 集合级 completeness publication；
- Host-private secret scanning ingress；
- directory staging/rename；
- runtime-owned session termination；
- CAS 和 concurrent-worker scheduler；
- persisted event ledger；

## 10. 当前状态语义

Plan 实际 `state` 只有：

```text
ROUTED
NEEDS_CLARIFICATION
WAITING_CAPABILITY
```

Plan 还包含 `workflow.states`，声明目标流程：

```text
CREATED -> ROUTED -> DOMAIN_RESEARCH -> MECHANISM_FROZEN
-> DATA_READY | WAITING_DATA -> IMPLEMENTING -> EVIDENCE_READY
-> COUNCIL_REVIEW -> ITERATE | REJECT | PROMOTE
```

这份列表目前是政策声明，不是已实现的状态机、CAS store 或自动转换器。

## 11. 当前脚本

### Build

```bash
python3 scripts/build_factorforge_research_org_plan.py \
  --workspace-root <factor_workspace> \
  [--request <request.json>] \
  [--preserve-existing]
```

默认 request 为 `identity/web_research_request.json`。Plan 已存在时，未提供 `--preserve-existing` 会 BLOCK；提供后只验证并保留，不按新 conversation 覆盖冻结计划。

无论 request 来自默认文件还是显式 `--request`，builder 都会把 Host 实际采用的有效 payload（补齐 factor/research/report/job identity 后）捕获为 `objects/research_organization/<report_id>/inputs/web_research_request.json`。Validator 从该快照重新运行 router，并要求结果与 frozen plan 完全一致。

### Admit one result

```bash
python3 scripts/admit_factorforge_agent_result.py \
  --workspace-root <factor_workspace> \
  --result <private-candidate-result.json> \
  [--role-id <role_id>]
```

相同结果重复提交是 idempotent；同一路径不同内容、身份/hash/status 映射错误、私有推理字段、未获准 fallback 或复用隔离 session 都会 BLOCK。

### Validate

```bash
python3 scripts/validate_factorforge_research_org.py \
  --workspace-root <factor_workspace> \
  [--require-results]
```

`--require-results` 要求 dispatch 中所有 task 的 result 都存在并通过 collection 校验。

### Smoke

```bash
python3 scripts/run_factorforge_research_org_smoke.py
```

当前 smoke 验证 bundle build/validate、混合路由、冻结 plan preservation 和 path escape BLOCK；它不启动真实 Agent。

## 12. Future Phases（非当前 MVP 验收）

### Phase 2：真实 Agent Runtime

- Codex/OpenClaw runtime adapter；
- task dependency scheduler；
- distinct session receipt；
- parallel dispatch/wait/retry；
- blind-context 与 session receipt 真实性检查。

### Phase 3：强化 Host Result Ingress

- runtime-to-Host private dropbox 和 signed session receipt；
- secret/MIME/size/filesystem-diff checks；
- complete-dispatch staging；
- directory-level atomic publication；
- immutable ingress receipts。当前只实现 caller-provided private JSON 的单结果验证与原子 admission。

### Phase 4：Ultimate Orchestration

- Step1-2 后自动 build plan；
- Director synthesis；
- measurement program freeze；
- Data delivery resume；
- Council adapter；
- persisted state、CAS 和 events ledger。

### Phase 5：Console 与生产验收

- runtime receipt 驱动的 Research Team 运行状态、attempt/history 和 Council proof；
- Fundamental/Price-Volume/Mixed golden cases；
- production-safe runtime isolation；
- formal proof eligibility integration。

上述能力只有代码、测试和独立 review 完成后才能升级为当前架构能力。

## 13. MVP 验收

当前 MVP 只验收：

1. plan 固定写到 `identity/research_organization_plan.json`；
2. dispatch/tasks/results/data_requests 路径都在 `objects/research_organization/<report_id>/`；
3. 不新增 workspace 顶层 `org/` required dirs；
4. Fundamental/Price-Volume active，Event/Macro capability gap fail closed；
5. hypothesis/research text 的路由权重大于 formula/code；
6. plan/registry/task/dispatch hash 和 workspace path guard 有效；
7. `--preserve-existing` 不改冻结 plan；
8. result envelope 与内层 domain proposal 层级正确；
9. private reasoning 和 false Council independence 被阻断；
10. Host admission 具有 hash/identity/status/path/session guard，结果冲突 fail closed；
11. bundle collection 自动阻断 isolated/independent session reuse；
12. Ultimate/workspace gate 能强制验证 plan，同时保留显式 legacy auto 边界；
13. Console 只按已验证结果投影 assurance，不能冒充 runtime 或 independence；
14. smoke/test 不写 shared data、repo-root knowledge 或其他 factor workspace。

MVP 验收不得声称真实多 Agent 已运行、Council 已完成或因子已通过正式研究。
