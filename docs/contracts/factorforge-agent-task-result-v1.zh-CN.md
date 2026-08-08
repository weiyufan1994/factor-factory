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

本合同的 base admission API 生成 task/dispatch、校验 result collection，并可由 Host 从 caller-provided 私有候选 JSON 原子 admit 单个 result。Phase 2 runtime 已在该 envelope 之上实现隔离 session、Host-private output 和 signed receipt；attachments quarantine 与 dispatch 级目录原子发布仍未实现。

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
<workspace>/staging/**
```

### 1.2 所有权语义

- Host builder 写 plan、captured input、task 和 dispatch manifest；
- task 的 `expected_result_path` 冻结 role result 的 canonical workspace path；
- Data Liaison task 的额外声明范围仅为当前 report 的 `data_requests/**`；隔离 Agent 仍只有 Host-private output 写权限，实际 request 由 Host 物化；
- `scripts/admit_factorforge_agent_result.py` 负责手工/外部候选 admission；正式 specialist runtime 使用 `scripts/run_factorforge_research_org_runtime.py` 和 Host-private signed receipt 链；
- Builder artifact 使用 temp file + `os.replace()`；result admission 在 frozen plan 文件锁下使用 temp file + atomic hard-link create，串行执行跨 role session 检查并禁止覆盖既有 canonical result。两者都不等于 complete-dispatch atomic publish。

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
  "result_ingress": {
    "mode": "host_validated_atomic_admission",
    "agent_direct_workspace_write_allowed": false,
    "admission_script": "scripts/admit_factorforge_agent_result.py"
  },
  "session_policy": {},
  "research_record_policy": {},
  "execution_stage_contract": {
    "stage": "pre_formal_research_design",
    "objective": "<role-specific objective>",
    "formal_backtest_evidence_available": false,
    "empirical_factor_verdict_allowed": false,
    "post_execution_empirical_council_owner": "factor-forge-step6"
  },
  "created_by": "factorforge_host_research_director",
  "task_sha256": "<64 lowercase hex>"
}
```

当前 validator 检查合同版本、hash、identity、plan binding、registry role snapshot、deterministic task ID、expected result/write scope、Host ingress policy 和 input artifact hash。Task 的 `input_artifacts` 还必须逐项等于 plan 冻结的 `input_snapshot_refs`。`tasks/` 必须精确等于 dispatch 引用集合，`results/` 只允许当前 required roles 的 expected result 文件；Data Liaison result 的 `generated_data_requests` 必须精确覆盖其 report-local `data_requests/` 普通文件集合。当前尚未实现完整 unknown-field allowlist。

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
- Builder 本身不运行 dependency scheduler，也不会改写冻结 task 的 `PENDING`。Phase 2 runtime 在 Host-private ledger 中维护动态 task state，并仍要求所有 `depends_on_roles` 已由 Host admit 且 status 为 `PASS`。

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

Intake/domain tasks 当前没有 task dependency。Task 文件中的 dependency 仍是冻结 policy；是否已满足由每次 Host admission 在 plan 文件锁内读取并验证 canonical predecessor results 决定，而不是靠 task status 字符串推断。

Independent Council task 还冻结 `required_review_role_ids`，其值为当前 `required_roles` 中除 Council 自身之外的完整有序列表。它比直接 dependency 更宽，用于约束 Council attestation 必须覆盖本轮全部 canonical role results。

## 5. Input Artifacts

Builder 始终捕获 Host 实际用于路由的有效 request payload，并对其余三个已存在文件生成 captured snapshot：

```text
host_request_payload
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
  "source_path": "host_request_payload",
  "source_hash_kind": "json_content",
  "source_sha256": "<captured payload sha256>",
  "captured_payload": {},
  "snapshot_sha256": "<json content sha256>"
}
```

其他文件快照的 `source_path` 是 workspace-relative file path，`source_hash_kind=file_bytes`，`source_sha256` 是源文件字节 SHA-256。

Task 的 `input_artifacts` 只引用：

```json
{
  "path": "objects/research_organization/REPORT_ID/inputs/web_research_request.json",
  "sha256": "<snapshot_sha256>",
  "hash_kind": "json_content"
}
```

Validator 要求 snapshot 为当前 workspace 内的普通文件、contract/hash 一致且不得是 symlink；对 Host request 还会验证有效 identity、重算 router，并要求 route 与 frozen plan 完全一致。

## 6. Scope 与 Session Policy

### 6.1 Scope

`read_scopes` / `write_scopes` 从 frozen role snapshot 展开 `<report_id>` 和 `<role_id>`。

每个 role 至少只可写自己的 result：

```text
objects/research_organization/<report_id>/results/<role_id>.json
```

Data Liaison task 还可声明：

```text
objects/research_organization/<report_id>/data_requests/**
```

Task validator 要求 `expected_result_path` 位于其 `write_scopes`。该 validator 本身不构成 runtime filesystem sandbox。Phase 2 adapter 只向 Agent 暴露 staged context、private output 和只读 canonical workspace；Data Liaison 必须内嵌 request payload，由 Host 校验、落盘并替换成 path/hash ref。当前仍没有覆盖所有进程级 side effect 的完整 filesystem-diff proof。

### 6.2 Session Policy

```json
{
  "requirement": "isolated_session",
  "independence_class": "domain_analysis",
  "single_agent_fallback_allowed": false
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

Builder 只冻结这些政策，不创建 session。Phase 2 runtime 才创建 session，并通过 adapter/Host signed receipt、provider handle uniqueness、owned termination 和 ledger binding 验证 `session_id`；只运行 builder 或基础 bundle validator 时不得声称获得该证明。

Runtime staging 使用 dependency 的传递闭包。已 admission dependency 的 public
`artifact_refs` 会在 path/hash 复核后一起进入只读 context，因此下游角色可以审计
Host Director 冻结的 plan，而不是只看到摘要。

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

## 7.1 Execution Stage Contract

当前 organization task 全部属于 `pre_formal_research_design`。Role-specific
objective 由 builder 冻结并由 validator 重算：

- Quant Implementation 审计 estimator、implementation route、timing 与 parity；
- Validation & Evidence 审计 IS/OOS、trial budget、成本、阈值、消融和 falsifier；
- Independent Council 独立审查完整执行前研究设计。

`formal_backtest_evidence_available=false` 与
`empirical_factor_verdict_allowed=false` 是硬边界。Organization Council 的 PASS
只允许 Host 进入 formal Ultimate，不等于 factor ACCEPT/REJECT；回测后 verdict
仍由 `factor-forge-step6` 及正式 proof certificate 决定。

Quant、pre-execution Validation 和 Independent Council 必须额外写
`factorforge_preformal_design_review_v3`。其中 `claim_scope` 必须精确为：

```json
{
  "stage": "pre_formal_research_design",
  "claim_domain": "research_design_only",
  "allowed_claim_types": ["DESIGN_REQUIREMENT"],
  "record_semantics": "controlled_design_checks_only",
  "free_text_claims_allowed": false,
  "realized_performance_evidence": false,
  "empirical_factor_verdict": "NOT_ISSUED",
  "promotion_authority": false
}
```

公开 record 只能包含 contract、canonical executive summary、claims、
artifact refs、固定 handoff 和 design review。`claims[]` 必须逐项等于有序
`checks[]`；每项只能包含 `check_id`、`claim_type=DESIGN_REQUIREMENT`、
`status=PASS|BLOCK`、受控 `finding_code`、受控 `falsifier_code` 和
`evidence_refs`。`blockers[]` 必须精确等于 status=BLOCK 的 check IDs。引用若非
task 冻结输入、task 自身或 admitted dependency result，或者没有对应
hash-bound `artifact_refs`，必须 BLOCK。

v3 不提供自由文本 claim/finding/falsifier/blocker，因此 completed simulation、
realized metric 或 promotion suitability 的自然语言改写没有可落盘通道；递归
语义扫描继续作为纵深防御。数值 preregistered threshold 应冻结在 Host plan 或
其 hash-bound design artifact 中，不写入 pre-formal verdict record。

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

该文件只是 **dispatch manifest**，其自身不产生 session/attempt/dispatch receipt，也不证明 policy 已由 runtime 执行。Phase 2 runtime 会另行生成并验证这些 receipt；dispatch manifest PASS 不能替代 runtime PASS。

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
    "reviewed_role_ids": ["research_director", "knowledge_librarian", "data_liaison", "price_volume_researcher", "quant_implementation", "validation_evidence"]
  }
}
```

普通 result 的根对象字段必须精确等于上面的九项。`independent_review` result
必须在这九项之外同时且仅增加 `independence_attestation` 与
`formal_independent_verdict`；任何 `factor_verdict`、`note` 或其他未声明根字段
都直接 BLOCK，即使提交者重新计算了 `result_sha256`。

根对象内的 `identity` 同样必须精确等于 frozen task identity 的 key/value 集；
不能在 `identity.factor_verdict`、`identity.note` 或其他额外 metadata 中藏入主张。

`independence_attestation` 的字段也必须精确为
`independence_satisfied`、`reviewed_role_ids`。所有 `artifact_refs[]` 必须精确为
`{path, sha256}`；Data Liaison materialize 后的 `generated_data_requests[]` 必须
精确为 `{request_id, path, sha256}`。这些相邻通道不得承载自由文本 verdict。

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

Data Liaison 不得用 result 宣称已 materialize data。数据可用性必须由 catalog/QA/delivery receipt 支撑。缺口在 Agent-private output 中以 `{request_id,path,request_payload}` 内嵌；Host 验证 `factorforge_data_request_v1`、consumer 和 report-local path 后原子落盘，并在 canonical result 中替换为 `{request_id,path,sha256}`。任何 validation、ledger 或 admission 失败都必须回滚本轮 Host-created request。

当 v2 Web catalog 含可用 entry 且 Data Liaison 返回 `PASS` 时，`catalog_resolution` 必须是闭合的 `factorforge_data_liaison_preformal_resolution_v1`：精确绑定 task 冻结的 catalog snapshot path/hash，至少声明一个 `design_time_reuse_hits[]`，每个 hit 只能引用 active admission hash 所绑定 catalog 内的 `base_market_dataset`，并精确匹配 S3 URI、字段子集、覆盖、Host information-policy attestation 与 producer provenance。Attestation 只从受控 `factorforge_information_policy_v1` 或已知 producer 的精确 PIT 合同生成；validator 会重算并比对，自由文本 presence 不能通过。`formal_execution_requirements` 固定为 `catalog_identity/dataset_qa/lookahead_policy/coverage/worker_read_smoke`，`formal_execution_gate` 固定为 `DEFERRED_TO_STEP3` 且不得授权执行，`generated_data_requests=[]`。派生 datamart/state、hash 错绑、缺检查、越界覆盖或额外字段均 BLOCK。

v2 catalog 为空或 snapshot 为 legacy 格式时，仅兼容旧 `{reuse_hits: [], generated_data_requests: []}` 加 `data_materialization=false` 的 no-data no-op；它不构成任何数据可用性声明。只要出现 reuse claim，该兼容口立即失效。

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
10. `artifact_refs` 的 exact shape、workspace-relative path、ordinary-file 和 SHA-256；
11. outer envelope、authority-bearing identity、Council independence attestation/formal verdict 和 canonical data-request ref 的 exact shape，以及 fallback overclaim；
12. domain/role identity、proposal status 到 envelope status 的映射；
13. Data Liaison 生成的 request path/file hash；
14. Data Liaison v2 pre-formal PASS 的 snapshot/catalog hash、base dataset、字段、覆盖、信息政策、provenance、deferred formal checks 与 read-only permission；
15. plan 禁止 fallback 时的 fallback result；
16. collection 中 isolated/independent role 的 peer-session reuse。

workspace-only bundle validator 当前不证明：

- Host runtime receipt 对 session ID 和 staged-context 的真实性；
- attachment MIME/size/secret scan；
- 普通 domain plugin 全部深层对象的 unknown-field strict JSON Schema closure；
- filesystem diff 与 declared write-set 对比。

需要 stronger proof 时，必须调用 `validate_research_organization_runtime()` 并提供 Host-private ledger/trust root。该 validator 能证明 signed session/staged-context binding，但仍不提供完整 filesystem-diff 或 attachment quarantine。

## 14. Council Independence 与 Fallback

当 task 的 `independence_class=independent_review`：

### `producer_mode=real_agent`

- 必须存在 `independence_attestation`；
- attestation 必须且只能包含 `independence_satisfied`、`reviewed_role_ids`；
- `independence_satisfied` 必须为 `true`；
- `reviewed_role_ids` 必须逐项等于 task 冻结的 `required_review_role_ids`；
- Council `session_id` 不得复用 collection 中其他 role 的 session。

### `producer_mode=single_agent_fallback`

当前 v1 plan 对所有 task 都生成 `single_agent_fallback_allowed=false`，因此任何当前 result 使用该 mode 都会先命中 `fallback_not_allowed`。以下规则保留为未来显式允许 fallback 时仍必须满足的独立性下界：

- `independence_satisfied` 必须为 `false`；
- result 不得包含 `formal_independent_verdict`；
- fallback result 不能证明 independent Council 已完成。

当前 bundle validator 会自动汇总全体已存在 result 的 peer session IDs；所有声明 `isolated_session` 或 `independent_session` 的 real Agent result 都不得复用 session。该校验不等于 runtime receipt 的真实性证明；formal runtime 还会验证 adapter/Host signatures、provider handle uniqueness、Council parent session 和 dependency event ordering。

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
- `--require-results`：额外要求 dispatch 中所有 task result 存在；
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

## 18. 合同外能力

以下能力是后续设计，不是当前合同验收项：

Phase 2 runtime 已实现独立 session、attempt/dispatch receipt、Host-private output、signed receipt、secret scan、retry/cancel/owned termination、dependency scheduler 和 persisted ledger。

仍未实现：

1. attachment quarantine 与 MIME validation；
2. complete-dispatch staging-directory rename；
3. 完整 declared filesystem-diff proof；
4. Director synthesis 和 measurement-program canonical merge；
5. Data delivery resume；
6. production factor research golden run。

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
10. Host 单结果 admission 和 collection session uniqueness 已闭环；本 task/result 合同 PASS 不替代 Phase 2 signed runtime PASS，也不声称 plan revision CAS 或 staging-directory atomic publish。
