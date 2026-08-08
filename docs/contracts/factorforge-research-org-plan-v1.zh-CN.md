# Factor Forge Research Org Plan v1 合同

## 0. 文档状态

本文定义当前已实现的 `factorforge_research_org_plan_v1`。当前 MVP 是 **workspace-local planning and validation proof**，不是自动多 Agent runtime、完整状态机或 production research proof。

当前唯一权威 plan 路径为：

```text
<factor_workspace>/identity/research_organization_plan.json
```

当前 MVP：

- 不新增 workspace 顶层 `org/`；
- 不创建 plan revision、`current.json` 或 companion state 文件；
- 不实现 compare-and-swap、events ledger 或 staging-directory rename；
- 不因 plan/dispatch 已生成而声称任何 Agent 已运行。

这些能力若保留为目标设计，只能放在本文的 Future Phase，不能进入当前验收。

## 1. 合同目的

Plan 由 Host/Research Director builder 一次性生成并冻结，回答：

- 本研究绑定哪个 `factor_id/research_id/report_id/job_id`；
- deterministic router 如何选择 lead/supporting domain；
- 当前 registry 中哪些角色 active、planned 或 unavailable；
- 哪些 role task 属于本次 bundle；
- Host、workspace、fallback、公开推导和 Data 组边界是什么；
- task、dispatch 和预期 result 应落到哪里。

Plan 不负责：

- 运行 Agent session；
- 自动推进 task dependency；
- 冻结具体 factor measurement program；
- 决定因子 `ITERATE/REJECT/PROMOTE`；
- 替代 Ultimate、Council、factor proof 或 production evidence。

Research Organization 的 `PASS` 仅表示组织合同通过验证。

## 2. Artifact 布局

当前 builder 使用以下布局：

```text
<factor_workspace>/
  manifest.json
  identity/
    web_research_request.json
    web_research_authoring_contract.json       # optional input
    factor_knowledge_summary.json               # optional input
    data_catalog_summary.json                   # optional input
    research_organization_plan.json             # Host frozen plan
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

`dispatch/tasks/results/data_requests` 全部位于：

```text
objects/research_organization/<report_id>/
```

Plan、task、dispatch 和 result 中的路径必须为当前 workspace 下的相对路径。Absolute path、`..`、symlink escape 和跨 factor 路径均不合法。

## 3. 顶层 Schema

当前 plan 的顶层字段如下：

```json
{
  "contract_version": "factorforge_research_org_plan_v1",
  "identity": {
    "factor_id": "FACTOR_ID",
    "research_id": "RESEARCH_ID",
    "report_id": "REPORT_ID",
    "job_id": "JOB_ID"
  },
  "state": "ROUTED",
  "generated_at_utc": "2026-08-08T00:00:00Z",
  "generated_by": "factorforge_host_research_director",
  "routing": {},
  "agent_registry": {},
  "role_plan": {},
  "execution_policy": {},
  "workflow": {},
  "data_team_interface": {},
  "workspace_policy": {},
  "plan_sha256": "<64 lowercase hex>"
}
```

当前 validator 检查必需合同语义、hash、identity、route、registry、role、policy 和路径；它尚未实现完整 JSON Schema unknown-field closure。不得在文档或验收中把“未知字段全部 fail closed”描述为当前能力。

## 4. Identity

### 4.1 字段

```json
{
  "factor_id": "FACTOR_ID",
  "research_id": "RESEARCH_ID",
  "report_id": "REPORT_ID",
  "job_id": "JOB_ID"
}
```

来源规则：

- `factor_id`、`research_id` 取自 workspace manifest；
- request 若显式提供这两个字段，必须与 workspace 完全一致；
- `report_id` 优先取 request，缺失时取 manifest 的 active report；
- `job_id` 优先取 request，缺失时为 `local_research`；
- 四个值都必须满足 safe ID 规则，禁止 `..`。

Plan 验证时，`factor_id/research_id` 必须与当前 workspace manifest 一致。CLI/request 不得覆盖已冻结 plan identity。

## 5. Plan State

当前 `state` 只允许：

```text
ROUTED
NEEDS_CLARIFICATION
WAITING_CAPABILITY
```

映射规则：

| Router state | Plan state |
|---|---|
| `ROUTED` | `ROUTED` |
| `ROUTED_WITH_CAPABILITY_GAP` | `ROUTED` |
| `UNDER_SPECIFIED` | `NEEDS_CLARIFICATION` |
| `WAITING_CAPABILITY` | `WAITING_CAPABILITY` |

Plan 中的 `workflow.states` 只是目标流程声明，不是已实现的 persisted state machine。当前没有 CAS transition、state revision、event append 或恢复执行器。

## 6. Routing

### 6.1 合同

`routing.contract_version` 为：

```text
factorforge_research_domain_route_v1
```

当前 payload 包含：

```json
{
  "contract_version": "factorforge_research_domain_route_v1",
  "routing_input_sha256": "<64 lowercase hex>",
  "routing_input_projection": {
    "sources": [],
    "source_count": 0
  },
  "route_state": "ROUTED",
  "lead_domain": "fundamental",
  "supporting_domains": ["price_volume"],
  "routing_confidence": "high",
  "domain_scores": {},
  "evidence": [],
  "capability_gaps": [],
  "routing_policy": {
    "economic_and_research_text_precedes_formula_or_code": true,
    "operator_names_do_not_select_math_family": true,
    "mixed_routes_allow_independent_parallel_proposals": true,
    "unsupported_lead_domain_fails_closed": true
  }
}
```

允许的 route states：

```text
ROUTED
ROUTED_WITH_CAPABILITY_GAP
UNDER_SPECIFIED
WAITING_CAPABILITY
```

允许的 confidence：

```text
none
low
moderate
high
```

### 6.2 当前算法边界

当前 router 是 transparent deterministic weighted term scorer，不是 LLM semantic router。来源权重：

| Source | Weight |
|---|---:|
| `hypothesis` | 4.0 |
| `title` | 3.0 |
| `research_direction` | 3.0 |
| `decision` | 3.0 |
| `report` | 2.5 |
| `formula` | 1.0 |
| `code` | 1.0 |

因此经济假设和研究文本优先于公式/代码，但当前 MVP 不能声称 router 已完成深层 economic hypothesis 建模。

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

Unsupported lead domain 进入 `WAITING_CAPABILITY`；无有效 domain signal 进入 `UNDER_SPECIFIED`。

## 7. Embedded Agent Registry

Plan 内嵌完整 registry snapshot：

```json
{
  "contract_version": "factorforge_agent_registry_v1",
  "roles": [],
  "registry_sha256": "<64 lowercase hex>"
}
```

当前 active roles：

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

当前 planned roles：

```text
event_researcher
macro_cross_asset_researcher
```

每个 role snapshot 包含 role ID/status、capability、activation、skills、input/output contracts、read/write scopes、model policy、independence class、session requirement、allowed tools 和 forbidden side effects。

`isolated_session` / `independent_session` 在当前 MVP 中是冻结的执行政策，不是 session 已创建的证明。Registry 直接嵌入 plan，不另写 `org/registry` snapshot。

## 8. Role Plan

```json
{
  "required_roles": [],
  "deferred_roles": [],
  "unavailable_roles": [],
  "domain_role_assignments": {
    "fundamental": "fundamental_researcher"
  }
}
```

规则：

- intake roles 为 `research_director`、`knowledge_librarian`、`data_liaison` 和已选 active domain roles；
- 正常 `ROUTED` 时加入 `quant_implementation`、`validation_evidence`、`independent_council`；
- `UNDER_SPECIFIED` 或 `WAITING_CAPABILITY` 时，下游三个角色进入 `deferred_roles`；
- selected domain 尚未 active 时进入 `unavailable_roles`；
- `required_roles` 必须存在且都在 registry 中为 active。

Role plan 是 task generation plan，不是角色已执行或已满足的声明。

## 9. Execution Policy

当前 builder 固定写入：

```json
{
  "one_user_task_per_factor": true,
  "one_isolated_factor_workspace": true,
  "domain_agents_use_isolated_sessions": true,
  "host_is_only_canonical_merger": true,
  "single_agent_fallback": false,
  "fallback_must_be_explicit": true,
  "fallback_cannot_claim_independent_council": true,
  "private_chain_of_thought_forbidden_in_artifacts": true,
  "public_derivation_and_decisive_steps_required": true
}
```

当前 validator 至少要求：

- 一个用户因子任务；
- 一个隔离 factor workspace；
- Host 是唯一 canonical merger；
- `single_agent_fallback=false`；
- artifact 禁止 private chain-of-thought。

当前没有 fallback scheduler。Result 可以声明 `producer_mode=single_agent_fallback`，但不能据此冒充 independent Council；详细规则见 Agent Task / Result 合同。

## 10. Workflow Declaration

Plan 声明的目标 states：

```text
CREATED
ROUTED
DOMAIN_RESEARCH
MECHANISM_FROZEN
DATA_READY
WAITING_DATA
IMPLEMENTING
EVIDENCE_READY
COUNCIL_REVIEW
ITERATE
REJECT
PROMOTE
```

并声明：

```json
{
  "waiting_data_is_nonterminal": true,
  "promotion_requires_independent_council": true
}
```

这些是 policy declarations。当前 MVP 不持久化 organization state，不自动执行 transition，也不把 list 中任一状态解释为已经到达。

## 11. Data Team Interface

```json
{
  "mode": "external_contract_only",
  "data_liaison_may_materialize_data": false,
  "request_contract": "data_request_v1",
  "accepted_delivery_evidence": [
    "catalog_entry",
    "qa_summary",
    "delivery_receipt"
  ],
  "missing_data_state": "WAITING_DATA"
}
```

含义：

- Data 组是外部合同协作者，不是本 workspace 内的数据生产角色；
- Data Liaison 可解析 catalog 和形成 `data_request_v1`；
- Data Liaison 不得 materialize datamart、改 catalog 或写 shared data；
- 当前 MVP 没有 delivery import/resume 执行器。

## 12. Workspace Policy

当前字段和值：

```json
{
  "plan_path": "identity/research_organization_plan.json",
  "organization_root": "objects/research_organization/<report_id>",
  "dispatch_manifest_path": "objects/research_organization/<report_id>/dispatch_manifest.json",
  "task_root": "objects/research_organization/<report_id>/tasks",
  "result_root": "objects/research_organization/<report_id>/results",
  "all_writes_under_factor_workspace": true,
  "cross_factor_reads_or_writes_allowed": false
}
```

当前 plan 不把 `data_requests` 单独存为 policy 字段，但 Data Liaison registry write scope 明确允许：

```text
objects/research_organization/<report_id>/data_requests/**
```

MVP 不修改 workspace initializer 的 required directories。目录由 artifact writer 按需在当前 workspace 内创建。

## 13. Content Hash 与冻结语义

`plan_sha256` 的计算：

1. 从对象中排除 `plan_sha256`；
2. JSON 使用 UTF-8、key sort 和 compact separators；
3. 计算 SHA-256；
4. 写回 64 位 lowercase hex。

当前写入使用临时文件加 `os.replace()` 做单文件替换。它只提供单文件写入边界，不代表 bundle/dispatch 目录级原子发布。

冻结规则：

- plan 已存在且未传 `--preserve-existing`：BLOCK；
- 传入 `--preserve-existing`：验证已有 bundle，并要求 request identity 与已有 plan 一致；
- preserve 模式不会根据后续 conversation 重写 plan；
- 当前没有 plan revision/supersedes chain。需要改变冻结计划时必须由 Future Phase 明确定义迁移与版本策略，不能静默覆盖。

## 14. Builder 与 Validator

### 14.1 Build

```bash
python3 scripts/build_factorforge_research_org_plan.py \
  --workspace-root <factor_workspace> \
  [--request <request.json>] \
  [--preserve-existing]
```

默认 request：

```text
identity/web_research_request.json
```

正常 build 写入：

- frozen plan；
- 当前存在的四类 input snapshot；
- required role tasks；
- dispatch manifest。

它不写 Agent result，也不运行 Agent。

### 14.2 Validate

```bash
python3 scripts/validate_factorforge_research_org.py \
  --workspace-root <factor_workspace> \
  [--require-results]
```

Validator 检查：

- workspace manifest 与 plan identity；
- plan/registry/dispatch/task content hash；
- route、role 和 execution policy；
- workspace-relative paths；
- input snapshot existence/hash；
- 已存在 result 的 envelope/payload；
- `--require-results` 时 READY task 的 result 是否存在。

当前 `--require-results` 不要求 PENDING task 的 result，也不会自动推进 dependency。

### 14.3 Smoke

```bash
python3 scripts/run_factorforge_research_org_smoke.py
```

Smoke 仅验证 build/validate、mixed-domain route、frozen plan preservation 和 path escape blocker，不启动真实 Agent 或 production research。

## 15. Blocker Tokens

当前实现定义：

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

CLI 将合同错误写到 stderr 并以非零 return code 退出。顶层错误可能以 plan-invalid 聚合多个底层原因；验收应保留完整原因链。

## 16. Future Phases（非当前 MVP、未实现）

以下设计可以继续演进，但不得作为当前合同验收项：

1. Plan revisions、`current.json` pointer 和 supersedes chain；
2. persisted organization state、state revision、CAS 和 append-only events；
3. real Agent runtime adapter、session receipt、parallel dispatch/retry/cancel；
4. Host-private ingress、secret scan、complete-dispatch staging 和 directory rename；
5. collection-level peer-session uniqueness/blindness；
6. Director synthesis、measurement program freeze 和 Ultimate state advancement；
7. Data delivery import/resume；
8. Console Research Team projection；
9. production factor research 与 formal proof eligibility integration。

## 17. 当前 MVP 验收

当前 plan 合同只验收：

1. 固定 plan 路径为 `identity/research_organization_plan.json`；
2. identity 与 workspace manifest 对齐；
3. route/registry/role plan 可重复且可验证；
4. `single_agent_fallback=false`，Host 是唯一 canonical merger；
5. workspace policy 不逃出当前 factor workspace；
6. plan/task/dispatch/result 的 hash binding 有效；
7. `--preserve-existing` 不修改冻结 plan；
8. dispatch/tasks/results/data_requests 均在 `objects/research_organization/<report_id>/`；
9. 不新增 workspace 顶层 `org/` required dirs；
10. 验收结论不声称当前已实现 runtime、CAS、events、directory staging 或正式因子研究。
