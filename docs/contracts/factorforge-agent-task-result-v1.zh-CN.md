# Factor Forge Agent Task / Result v1 合同

## 0. 文档状态

本文定义当前已实现的三类 workspace-local artifact：

- `factorforge_agent_task_v1`：Host 为某个 role 生成的任务合同；
- `factorforge_research_org_dispatch_v1`：引用这些 task 的 dispatch manifest；
- `factorforge_agent_result_v1`：所有 Agent/role result 的统一外层 envelope。

领域插件 `factorforge_domain_research_proposal_v1` 不与 result envelope 并列，也不替代 envelope。它必须作为外层 result 的：

```text
factorforge_agent_result_v1.public_research_record
```

当前 MVP 生成 task/dispatch，并能校验已有 result；它不创建真实 Agent session，不实现 Host-private ingress、attachments staging 或 dispatch 级目录原子发布。

## 1. 当前路径与所有权

### 1.1 固定布局

```text
<factor_workspace>/
  identity/
    research_organization_plan.json
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

当前不使用以下路径：

```text
<workspace>/org/**
<host_private_root>/**
<workspace>/staging/**
```

### 1.2 所有权语义

- Host builder 写 plan、captured input、task 和 dispatch manifest；
- task 的 `expected_result_path` 冻结 role result 的 canonical workspace path；
- Data Liaison 的额外 write scope 仅为当前 report 的 `data_requests/**`；
- 当前代码只验证结果文件，不实现真实 Agent 到 Host-private ingress 的传输；
- 当前单文件写入使用 temp file + `os.replace()`，不等于 complete-dispatch atomic publish。

## 2. Agent Task v1

### 2.1 路径与命名

```text
objects/research_organization/<report_id>/tasks/task_<nn>_<role_id>.json
```

Task ID 格式：

```text
task_<two-digit-sequence>_<role_id>
```

示例：

```text
task_04_price_volume_researcher
```

### 2.2 顶层 Schema

当前 task 的字段为：

```json
{
  "contract_version": "factorforge_agent_task_v1",
  "task_id": "task_04_price_volume_researcher",
  "identity": {
    "factor_id": "FACTOR_ID",
    "research_id": "RESEARCH_ID",
    "report_id": "REPORT_ID",
    "job_id": "JOB_ID"
  },
  "plan_ref": {
    "path": "identity/research_organization_plan.json",
    "sha256": "<plan_sha256>"
  },
  "registry_sha256": "<registry_sha256>",
  "role_id": "price_volume_researcher",
  "role_snapshot": {},
  "phase": "domain_research",
  "status": "READY",
  "depends_on_roles": [],
  "input_artifacts": [],
  "read_scopes": [],
  "write_scopes": [],
  "expected_result_path": "objects/research_organization/REPORT_ID/results/price_volume_researcher.json",
  "result_envelope_contract": "factorforge_agent_result_v1",
  "output_contract": "factorforge_domain_research_proposal_v1",
  "session_policy": {},
  "research_record_policy": {},
  "created_by": "factorforge_host_research_director",
  "task_sha256": "<64 lowercase hex>"
}
```

当前 validator 检查合同版本、hash、identity、plan binding、registry role snapshot、expected result/write scope 和 input artifact hash。当前尚未实现完整 unknown-field allowlist。

## 3. Task Binding

### 3.1 Identity

Task 的 `identity` 必须逐字段等于 frozen plan identity：

```text
factor_id
research_id
report_id
job_id
```

Result 必须再次绑定同一 identity。

### 3.2 Plan Reference

当前 `plan_ref` 必须精确等于：

```json
{
  "path": "identity/research_organization_plan.json",
  "sha256": "<current frozen plan_sha256>"
}
```

当前没有 plan revision、current pointer 或 supersedes chain。

### 3.3 Registry Binding

- `registry_sha256` 必须等于 plan 内嵌 registry 的 hash；
- `role_id` 必须在 registry 中为 active；
- `role_snapshot` 必须逐字段等于 registry 中对应 role；
- Agent 不得通过 result 扩大 role scope、tool 或 side-effect 权限。

## 4. Phase、Status 与依赖

### 4.1 Phase

当前 builder 映射：

| Role | Phase |
|---|---|
| `research_director` | `intake` |
| `knowledge_librarian` | `intake` |
| `data_liaison` | `intake` |
| `*_researcher` | `domain_research` |
| `quant_implementation` | `implementation` |
| `validation_evidence` | `validation` |
| `independent_council` | `council` |

### 4.2 Task Status

当前 builder 只写：

```text
READY
PENDING
```

- 没有 dependency 的 task 为 `READY`；
- 有 dependency 的 task 为 `PENDING`；
- 当前 MVP 不实现 dependency scheduler，不会自动把 `PENDING` 更新为 `READY`。

### 4.3 Dependency 规则

```text
quant_implementation
  <- active domain researchers
  <- knowledge_librarian
  <- data_liaison
  <- research_director

validation_evidence
  <- quant_implementation

independent_council
  <- validation_evidence
  <- research_director
```

Intake/domain tasks 当前没有 task dependency。Dependency 是 manifest policy，不是 predecessor 已完成的证明。

## 5. Input Artifacts

Builder 对以下已存在的文件生成 captured snapshot：

```text
identity/web_research_request.json
identity/web_research_authoring_contract.json
identity/factor_knowledge_summary.json
identity/data_catalog_summary.json
```

Captured snapshot 路径：

```text
objects/research_organization/<report_id>/inputs/<source-filename>
```

Snapshot 合同：

```json
{
  "contract_version": "factorforge_research_org_input_snapshot_v1",
  "source_path": "identity/web_research_request.json",
  "source_sha256": "<source file sha256>",
  "captured_payload": {},
  "snapshot_sha256": "<json content sha256>"
}
```

Task 的 `input_artifacts` 只引用：

```json
{
  "path": "objects/research_organization/REPORT_ID/inputs/web_research_request.json",
  "sha256": "<snapshot_sha256>",
  "hash_kind": "json_content"
}
```

Validator 要求 snapshot 为当前 workspace 内的普通文件、contract/hash 一致且不得是 symlink。

## 6. Scope 与 Session Policy

### 6.1 Scope

`read_scopes` / `write_scopes` 从 frozen role snapshot 展开 `<report_id>` 和 `<role_id>`。

每个 role 至少只可写自己的 result：

```text
objects/research_organization/<report_id>/results/<role_id>.json
```

Data Liaison 还可写：

```text
objects/research_organization/<report_id>/data_requests/**
```

Task validator 要求 `expected_result_path` 位于其 `write_scopes`。当前代码未实现 runtime filesystem sandbox；这些 scope 是可验证合同和后续 runtime 的执行要求，不能描述成当前已经阻断所有进程级 side effect。

### 6.2 Session Policy

```json
{
  "requirement": "isolated_session",
  "independence_class": "domain_analysis",
  "single_agent_fallback_allowed": true
}
```

Independent Council 示例：

```json
{
  "requirement": "independent_session",
  "independence_class": "independent_review",
  "single_agent_fallback_allowed": false
}
```

当前 builder 只冻结这些政策，不创建 session。`session_id` 的真实性和 runtime ownership 尚无 Host receipt 支撑。

## 7. Research Record Policy

每个 task 固定：

```json
{
  "public_derivation_required": true,
  "private_chain_of_thought_forbidden": true,
  "claims_require_artifact_or_falsifier_refs": true
}
```

允许且要求公开：

- economic claim；
- 数学对象与关键推导；
- decisive assumptions；
- alternative/null model；
- falsifier；
- evidence/artifact reference；
- uncertainty 和 handoff。

禁止写入 artifact：

```text
chain_of_thought
chainofthought
cot
hidden_reasoning
private_reasoning
reasoning_trace
scratchpad
```

Validator 递归扫描这些 key。禁止 private CoT 不等于禁止可审计的公开数学推导。

## 8. Output Contract Mapping

当前 role 的 `output_contract`：

| Role type | Inner payload contract |
|---|---|
| Fundamental / Price-Volume domain Agent | `factorforge_domain_research_proposal_v1` |
| Data Liaison | `factorforge_domain_research_proposal_v1`（专用字段集） |
| Director / Knowledge / Implementation / Evidence / Council | `factorforge_role_research_record_v1` |
| Event / Macro | planned，当前不生成 active task |

无论 inner payload 是哪一种，外层始终是 `factorforge_agent_result_v1`。

## 9. Dispatch Manifest

### 9.1 路径

```text
objects/research_organization/<report_id>/dispatch_manifest.json
```

### 9.2 Schema

```json
{
  "contract_version": "factorforge_research_org_dispatch_v1",
  "identity": {},
  "plan_ref": {
    "path": "identity/research_organization_plan.json",
    "sha256": "<plan_sha256>"
  },
  "state": "ROUTED",
  "tasks": [
    {
      "task_id": "task_01_research_director",
      "role_id": "research_director",
      "phase": "intake",
      "status": "READY",
      "path": "objects/research_organization/REPORT_ID/tasks/task_01_research_director.json",
      "sha256": "<task_sha256>",
      "expected_result_path": "objects/research_organization/REPORT_ID/results/research_director.json"
    }
  ],
  "dispatch_policy": {
    "independent_sessions_for_non_host_roles": true,
    "parallelize_ready_tasks": true,
    "host_validates_before_merge": true,
    "do_not_create_user_visible_threads": true
  },
  "dispatch_sha256": "<64 lowercase hex>"
}
```

该文件只是 **dispatch manifest**。当前 MVP 不产生 session/attempt/dispatch receipt，也不证明 policy 已由 runtime 执行。

## 10. Agent Result v1 外层 Envelope

### 10.1 路径

```text
objects/research_organization/<report_id>/results/<role_id>.json
```

### 10.2 当前 Schema

```json
{
  "contract_version": "factorforge_agent_result_v1",
  "task_ref": {
    "task_id": "task_04_price_volume_researcher",
    "sha256": "<task_sha256>"
  },
  "identity": {
    "factor_id": "FACTOR_ID",
    "research_id": "RESEARCH_ID",
    "report_id": "REPORT_ID",
    "job_id": "JOB_ID"
  },
  "role_id": "price_volume_researcher",
  "status": "PASS",
  "producer_mode": "real_agent",
  "session_id": "agent_session_1",
  "public_research_record": {},
  "result_sha256": "<64 lowercase hex>"
}
```

Council result 还可包含：

```json
{
  "independence_attestation": {
    "independence_satisfied": true,
    "reviewed_role_ids": []
  }
}
```

### 10.3 Allowed Values

Result status：

```text
PASS
BLOCK
NEEDS_DATA
NEEDS_CLARIFICATION
```

Producer mode：

```text
real_agent
single_agent_fallback
```

`PASS` 仅表示此 role result 通过其合同语义，不等于 factor、Council 或 production proof `ACCEPT`。

## 11. Domain Proposal Plugin

### 11.1 正确嵌套

```json
{
  "contract_version": "factorforge_agent_result_v1",
  "public_research_record": {
    "contract_version": "factorforge_domain_research_proposal_v1",
    "identity": {},
    "domain": "price_volume",
    "proposal_status": "ready_for_director_review",
    "domain_fit": {},
    "public_research_record": {
      "public_derivation_summary": []
    },
    "math_model_search": {},
    "measurement_proposal": {},
    "knowledge_use": [],
    "data_dependencies": [],
    "falsification_plan": {},
    "uncertainties": [],
    "artifact_refs": [],
    "handoff": {}
  }
}
```

层级解释：

```text
factorforge_agent_result_v1                         # outer envelope
  public_research_record                            # domain plugin object
    contract_version = factorforge_domain_research_proposal_v1
    public_research_record                          # plugin 内公开推导记录
      public_derivation_summary
```

不能把 `factorforge_domain_research_proposal_v1` 作为 envelope 同级对象，也不能直接把 plugin 当成 result 文件根对象。

### 11.2 普通领域 proposal 最低字段

```text
identity
domain
proposal_status
domain_fit
public_research_record
knowledge_use
data_dependencies
uncertainties
handoff
math_model_search
measurement_proposal
falsification_plan
```

该合同意图要求 mechanism-conditioned open math search；它不固定随机过程、DCF、信号处理或量纲分析为所有因子的统一工具。

### 11.3 Data Liaison proposal 最低字段

Data Liaison 同样使用 `factorforge_domain_research_proposal_v1` contract version，但使用专用字段集：

```text
identity
domain
proposal_status
domain_fit
catalog_resolution
delivery_receipt_verification
knowledge_use
permissions_boundary
uncertainties
handoff
```

Data Liaison 不得用 result 宣称已 materialize data。数据可用性必须由 catalog/QA/delivery receipt 支撑；缺口通过 `data_request_v1` 进入当前 report 的 `data_requests/`。

## 12. Role Research Record Plugin

非领域 role 的 `public_research_record` 使用：

```text
factorforge_role_research_record_v1
```

最低字段：

```json
{
  "contract_version": "factorforge_role_research_record_v1",
  "executive_summary": "Public, reproducible conclusion.",
  "claims": [],
  "artifact_refs": [],
  "handoff": {}
}
```

它仍位于 `factorforge_agent_result_v1.public_research_record`，不另建顶层 result contract。

## 13. Result Validation

当前 validator 检查：

1. outer contract version；
2. `result_sha256`；
3. `task_ref.task_id/sha256`；
4. identity 与 role ID；
5. result status 与 producer mode；
6. 非空 `session_id`；
7. inner payload contract version 必须等于 task 的 `output_contract`；
8. domain/data-liaison/role-record 的最低字段；
9. private reasoning key 的递归阻断；
10. `artifact_refs` 的 workspace-relative path、ordinary-file 和 SHA-256；
11. Council independence attestation 和 fallback overclaim。

当前未实现：

- Host runtime receipt 对 `session_id` 的真实性证明；
- bundle validator 自动汇总全部 peer session IDs；
- result collection 级 completeness/blindness；
- attachment MIME/size/secret scan；
- unknown-field strict JSON Schema closure；
- filesystem diff 与 declared write-set 对比。

## 14. Council Independence 与 Fallback

当 task 的 `independence_class=independent_review`：

### `producer_mode=real_agent`

- 必须存在 `independence_attestation`；
- `independence_satisfied` 必须为 `true`；
- 若调用 validator 时显式传入 peer session IDs，Council `session_id` 不得复用其中任何一个。

### `producer_mode=single_agent_fallback`

- `independence_satisfied` 必须为 `false`；
- result 不得包含 `formal_independent_verdict`；
- fallback result 不能证明 independent Council 已完成。

当前 bundle validator 调用 result validator 时没有自动传入全体 peer session IDs，因此 collection-level uniqueness 是 Future Phase，不能列为当前验收已闭环。

## 15. Content Hash

Task、dispatch、result 分别使用：

```text
task_sha256
dispatch_sha256
result_sha256
```

计算规则一致：

1. 排除自身 hash 字段；
2. UTF-8 JSON；
3. key sort；
4. compact separators；
5. SHA-256 lowercase hex。

File SHA-256 和 JSON content hash 语义不同。Captured JSON input 使用 `hash_kind=json_content`，validator 按 snapshot payload 的 content hash 校验。

## 16. 当前 Validator CLI 语义

```bash
python3 scripts/validate_factorforge_research_org.py \
  --workspace-root <factor_workspace> \
  [--require-results]
```

- 默认：验证 plan/dispatch/tasks，并验证已经存在的 results；
- `--require-results`：额外要求所有当前 `READY` task result 存在；
- `PENDING` task 不因缺 result 而在该选项下 BLOCK；
- validator 不运行 task，不更新 task status，也不推进 organization state。

## 17. Blocker Tokens

Task/result 相关实现使用：

```text
BLOCK_FACTORFORGE_RESEARCH_ORG_PATH_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_REGISTRY_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_TASK_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_RESULT_INVALID
BLOCK_FACTORFORGE_RESEARCH_ORG_INDEPENDENCE_INVALID
```

Bundle validator 可能将这些底层原因聚合到：

```text
BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID
```

验收时必须保留原因明细，不能只看顶层 token。

## 18. Future Phases（非当前 MVP、未实现）

以下能力是后续设计，不是当前合同验收项：

1. Agent runtime adapter 与独立 session 创建；
2. attempt/dispatch/session receipts；
3. Host-private ingress；
4. attachment quarantine、MIME/size/secret scan；
5. complete-dispatch staging-directory rename；
6. result collection completeness 与 peer-session uniqueness；
7. retry/cancel/owned-session termination；
8. task dependency scheduler 与 persisted state transitions；
9. Director synthesis 和 canonical merge pipeline；
10. Console/UI 的 role progress projection。

## 19. 当前 MVP 验收

当前 task/result 合同只验收：

1. task 位于 `objects/research_organization/<report_id>/tasks/`；
2. expected result 位于同一 report 的 `results/<role_id>.json`；
3. Data Liaison 只能额外写同一 report 的 `data_requests/**`；
4. task identity、plan、registry、role、input 和 write scope binding 有效；
5. dispatch 引用 task path/hash 和 expected result path；
6. `factorforge_agent_result_v1` 始终是 outer envelope；
7. `factorforge_domain_research_proposal_v1` 位于 outer `public_research_record`；
8. inner contract、最低字段、artifact hash 和 private reasoning guard 有效；
9. fallback Council 不得声称独立 verdict；
10. 不声称当前已实现真实 session、Host ingress、CAS/events 或 staging-directory atomic publish。
