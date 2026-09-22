# Factor Forge Epistemic Host Readback Stage1B-0 Meta-Contract V1

## 1. 身份与结论上限

本合同只闭合 `Stage1B-0`：Host deployment readback 的控制面身份、工件链、签名边界和状态裁决律。
它是 candidate design bytes，不是 Host deployment receipt，也不授权实现 collector、生成 key、签名、
读取 live Host、执行 independent verifier，或改变任何 deployment row。

冻结输入为：

| 对象 | Exact identity |
|---|---|
| P0 packet | `FACTORFORGE_EPISTEMIC_GRAPH_V2_P0_BINDING_REVIEW_20260822_R2` |
| P0 manifest SHA-256 | `58c3585881f52c4ed60c4e7fb582e9b30acf0063433c12363915d54f0b985c4f` |
| Stage1A final commit | `07850b6886380aa961e1507d8f3a8df91fe204a6` |
| Stage1A contract SHA-256 | `00fa469e89b8604ce483309d2f40edd1723dbfa86f385c9aa3da6e9433e69eda` |
| Stage1A module SHA-256 | `5e9e5b1cda23686dc6bb0be3e6f8826f013f39ce509f34b017f7ae337f396fa1` |
| Stage1A builder SHA-256 | `91197f06f5b68743ca7f8a78edacc8b66583e517fdbb2b86dbd80f18122f2399` |
| Stage1A validator SHA-256 | `4cba712c9603ff1a80bcdd5b3191345ab83926478f58ff0fce3ee0d16bf141b3` |
| Stage1A expected-inventory content SHA-256 | `594033b27960eb97da203b3d2706300b35cb69178c1adf5f41012540e8da2856` |
| current operating-code baseline | `dc6f55ab6ea1f9dc32518e3af02df4a9e5d423ee` |
| Closed-schema bundle `$id` | `urn:factorforge:schema:epistemic-host-readback-closed-bundle:v1` |
| Closed-schema bundle raw file SHA-256 | `43d33b4499a82e69183cc5f0f8f3df116fb97545c892f44f098b9b81cac8e316` |
| Closed-schema bundle design status | `STAGE1B0_CANDIDATE_BYTES_ONLY__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING` |

本合同最高合法裁决是：

```text
STAGE1B0_META_DESIGN_GO__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING
STAGE1B0_META_DESIGN_REVISE
```

即使得到第一个裁决，所有 Stage1B implementation authority 仍为 `false`。它不能被解释为
`BOUND_VERIFIED`、Host readback 完成、P1A、RAG、Skill、shadow、runtime、canonical write 或 OOS
授权。

## 2. 为什么必须有 Stage1B-0

冻结 P0 已规定 Host sanitized readback 要证明的对象和字段，但没有冻结以下 meta-authority：

1. unsigned Host target 的 closed schema；
2. deployment attestation issuer 的 principal/context/capability/key/trust row；
3. detached receipt 的 canonicalization、signature input 和 self-hash exclusion；
4. independent verifier 的 principal、SoD、target 和 receipt；
5. 单行和全 snapshot 的 effective-status 聚合律。

P0 的全部 runtime/action role 行都固定 `deployment_authority_const=false`。因此 Agent、Step6、Council、
`FF_SNAPSHOT_ISSUER_V1` 或 current generic `host_admission` key 均不能自行补齐上述控制面身份。

当前 source audit 也得到：

```text
COMPLETE_REAL_BINDABLE_P0_ROWS = 0
```

现有 canonical memory/CAS、generic Ed25519 和 current EVO 是可复用 seam，但都没有完整闭合
physical identity、purpose-specific principal/context/capability/key、trust/nonrevocation、detached receipt
及 independent verifier。代码存在不等于 deployment binding。

## 3. 控制面不是第二个 canonical authority

候选控制面 ID：

```text
FF_EPISTEMIC_DEPLOYMENT_EVIDENCE_CONTROL_PLANE_V1
```

它只有 deployment-evidence attestation authority，不拥有：

- canonical experience admission、review 或 promotion；
- Factor Forge research semantic authoring；
- factor proof、EVO lifecycle、OOS 或 data-release authority；
- Agent delivery、RAG ranking、Council 或 Step1–6 execution authority；
- Skill、operating contract、schema baseline 或 P0 registry mutation authority。

控制面 session chain 必须从一个只能由 Host protected configuration loader 读取的
`factorforge_epistemic_host_readback_bootstrap_pin_set_v1` 开始。该 pin set exact bind 四个两两不同的
trust-manifest SHA/generation/anchor：Host session chain、independent verifier chain、external phase
authorization、external isolation attestation；同时绑定两个 external issuer 的
principal/context/capability/key。请求、response 或 packet 中同形状 bytes 不能替代这个 out-of-band trusted
input。response 内自报的 manifest、key、role、path 或 authority label 不能 bootstrap 自己；两个 externally
pinned prerequisite trust stewards 都不是本次五个 control-plane action/content roles，也不是167个被绑定
subjects。

## 4. 五个候选控制面角色

### 4.1 Session issuer

```text
FF_DEPLOYMENT_READBACK_SESSION_ISSUER_V1
```

只允许在 external authorization steward 已签发 `STAGE1B_SESSION_CHALLENGE_ISSUANCE` grant 后，复制其
exact `authorization_context` 并签一个 one-shot challenge。它不能选择或缩减 trust pin、subject universe、
proof/collision manifest、code/config allowlist、policy 或 expected control head；也不能读取 Host deployment、
author target、签 attestation 或做 binding verification。

### 4.2 Content-provenance-signing collector

```text
FF_DEPLOYMENT_READBACK_TARGET_COLLECTOR_V1
```

只允许在 Host-private boundary 内只读 approved deployment metadata，构造一个 action-unsigned、但
content-provenance-signed 的 sanitized target。
它可以在 Host 内部观察 private locator，但不能输出 locator、原始 identity component 或 payload；不能持有
session/attestation/verdict control-action key，也不能签发 effective status。它只持有与自身
principal/context/capability 预先绑定的 content-provenance key；该 key 只能证明 target bytes 的作者，不能
产生 deployment、binding 或 runtime authority。

collector 必须是新 non-mutating scanner。现有 `validate_researcher_memory_store` 会执行 recovery、清理
transaction/temp state，因此结构上禁止被 Stage1B collector 调用。collector 不得 initialize、repair、
migrate、recover、lock-for-write、touch atime-sensitive payload、创建 missing directory 或生成 default。

### 4.3 Host attestation issuer

```text
FF_DEPLOYMENT_READBACK_ATTESTATION_ISSUER_V1
```

只签一个已冻结 action-unsigned/content-provenance-signed target 与 exact challenge。它不能编辑 target、验证自己的 attestation、签发
runtime authority 或把 incomplete row 标为 `BOUND_VERIFIED`。

### 4.4 Independent verification-target author

```text
FF_DEPLOYMENT_VERIFICATION_TARGET_AUTHOR_V1
```

在独立 Host/OS-enforced context 中重新读取、复算并构造 action-unsigned、content-provenance-signed
verification target。它不能签最终 verifier receipt、修改 Host target/receipt 或 observed deployment，也
不能持有 control-action key。其 content-provenance key 只证明 verification-target bytes 的作者。

### 4.5 Independent verifier

```text
FF_DEPLOYMENT_BINDING_INDEPENDENT_VERIFIER_V1
```

只审查并签一个已由独立 verification-target author 冻结的 exact verification target。它不能 author
verification target、修改 observed deployment、target 或 Host receipt。

caller-supplied reviewer label、不同函数名、不同 process label、同一 session 或同 UID 均不是独立性证明。

## 5. SoD 与 bootstrap law

下列约束全部为硬约束：

1. session issuer、collector、Host attestation issuer、verification-target author、verifier 的 resolved
   principal/context/capability 均不等；
2. collector 与 verification-target author 不持有任何 control-action signing key，但必须分别使用
   purpose-specific content-provenance key 签名其 target bytes；
3. session、collector-content、attestation、verification-author-content、verifier 五把 key 两两不等；
   content-provenance key 结构上不能签 challenge、Host attestation 或 verifier verdict；
4. Host attestation 与 independent verifier 使用两个不同的 out-of-band trust-manifest pins；
5. externally pinned trust steward 不是本 packet action role，且其 trust/nonrevocation state 必须在本次
   session 前存在；
6. Agent、Step6、Council、RAG executor 和 P0 subject roles 都不能成为控制面 role；
7. `FF_SNAPSHOT_ISSUER_V1` 是被绑定的 R3 subject，不能签自己的 deployment bootstrap；
8. current `factorforge_research_org_trust_manifest_v1` 只有 `runtime_adapter|host_admission` 两类 generic
   key，默认只能保持 `PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`；
9. 只有另行批准的 purpose-specific binding delta 才能复用已有 key；同一算法或同一 Host 不构成复用权；
10. 四个 trust manifests 必须先由 protected bootstrap pin set exact pin；四份 phase authorization receipt
    必须逐 byte 绑定同一个 authorization context，session issuer 只能复制、不能选择；
11. packet 内 manifest/key 自报、环境变量、默认路径、近似 installation ID 或 caller-selected fallback 无效。
12. verifier independence receipt 必须在 session 前由五个 control-plane roles 之外、out-of-band pin 的 trust
    authority 签发；五角色中的任一角色自签、互签或在 response 内临时创建该 receipt 均无效。
13. deployment phase authorization 与 isolation attestation 使用两个独立 external prerequisite trust
    domains，并与 Host/verifier 两个 session-chain domains 两两不等；冻结 R3
    `FF_PHASE_POLICY_ISSUER_V1` 与 `FF_IDENTITY_INDEPENDENCE_ATTESTATION_ISSUER_V1` 本身属于167个待绑定
    subjects，不能替代 external bootstrap stewards。
14. opaque `scope_allowlist_sha256` 不能替代 closed grant。四个 grant 必须分别是
    `STAGE1B_SESSION_CHALLENGE_ISSUANCE`、`STAGE1B1_LIVE_READBACK_EXECUTION`、
    `STAGE1B2_HOST_ATTESTATION`、`STAGE1B3_INDEPENDENT_VERIFICATION` 的 closed `oneOf` branch；任一缺失、
    重复、context 不同或 fallback 都 block。

这五个角色是 external candidate control-plane roles，不是冻结 R3 normative role universe 的增补；其
operating-contract delta 当前仍为未批准。Stage1B-0 只能冻结候选语义，不能令角色获得 deployment binding。

### 5.1 Trusted-input artifacts

在 challenge 之前必须已有、并由 closed schema 校验以下六类 trusted-input/dependency artifacts：

```text
bootstrap_pin_set
trust_manifest
nonrevocation_snapshot
subject_requirement_registry
physical_proof_applicability_manifest
protected_namespace_manifest
```

`subject_requirement_registry` 必须 exact materialize Stage1A 的167行顺序、static projection、baseline status、
161/6 partition 与七个 family requirement profiles。`physical_proof_applicability_manifest` 也必须在 session 前
materialize 同样167行；每行只能是 frozen `REQUIRED` backend set 或 frozen static-rule N/A，runtime discovery
不能自行判 N/A。`protected_namespace_manifest` 只含 session-purpose opaque commitments，不含 private locator。

每个 signature 的 nonrevocation 证明不能只是裸 head/hash：必须 reference exact
`factorforge_epistemic_deployment_control_nonrevocation_snapshot_v1` completed signed bytes，并携带从 bootstrap
anchor 到 signing head 的 closed append-only consistency path、tree sizes、cutoff 与 temporal-policy hash。

### 5.2 External control state

Stage1B 至少依赖两个预先存在、独立绑定的 control stores：

```text
FF_DEPLOYMENT_READBACK_CONTROL_LEDGER_V1
  factorforge_epistemic_deployment_readback_control_ledger_v1

FF_DEPLOYMENT_BINDING_VERIFICATION_REGISTRY_V1
  factorforge_epistemic_deployment_binding_verification_registry_v1
```

前者对 one challenge/target，后者对 one binding generation/verification target，分别执行同一无环协议：

```text
expected parent
  -> reserve exact target and intended action/verdict
  -> signer signs receipt binding reservation
  -> external ledger finalizes reservation to exact completed-signed-receipt digest
```

signed receipt 只含 reservation ID/head/receipt hash，不含后置 finalization result；finalization receipt只在后续
引用中出现。这样 ledger 可绑定 exact signed bytes 而不形成 receipt↔CAS hash cycle。后者的reservation还必须
执行 `NO_PRIOR_VERDICT_FOR_BINDING_GENERATION`，并固定唯一 terminal
`PASS|CHANGES_REQUESTED|REJECT`。两者必须在 session 前已获 out-of-band
physical/trust binding，并位于全部167个被证明 subject roots/endpoints 之外。把 control ledger 放进正在被
证明的 canonical-memory、transaction 或 delivery root 会形成 bootstrap cycle，必须拒绝。

reservation 与 finalization 不是 prose seam：分别由
`factorforge_epistemic_control_store_reservation_record_v1` 与
`factorforge_epistemic_control_store_finalization_record_v1` closed schema 固定。embedded reservation/ref 必须与
对应 record 的 exact content digest、store ID、generation、head、target/action 和 validator receipt逐字段相等。

本合同不创建这两个 stores；其 `deployment_binding=null` 时 Stage1B-1/2/3 均保持阻断。

## 6. Exact subject universe

任何 readback request、target 和 verification 都必须覆盖同一 closed universe：

| Subject family | Count |
|---|---:|
| authorities | 5 |
| root anchors | 3 |
| delivery endpoints | 2 |
| required physical relationships | 4 |
| stores | 12 |
| SoD profiles | 24 |
| principal rows | 33 |
| event-purpose rows | 67 |
| external-trust rows | 1 |
| deployment rows total | 101 |
| adapters | 40 |
| discriminated adapters | 38 |
| singleton adapters | 2 |
| material binding subjects total | 167 |

167 行的 family 顺序固定为：

```text
authorities
-> root_anchors
-> delivery_endpoints
-> required_relationships
-> stores
-> deployment_rows
-> adapters
```

family 内严格复用 exact Stage1A expected-inventory array order。`deployment_rows` 固定为
`principal_rows -> event_rows -> external_trust_rows`；`required_relationships` 固定为
`root_relationships -> delivery_endpoint_relationship`。不得按 runtime discovery、path、mtime 或调用方输入
重排。

每个 static subject projection 与 ordered-universe pin 固定为：

```text
static_subject_projection_sha256 = SHA256(
  UTF8("FFDB-SUBJECT-V1" + NUL + subject_family + NUL)
  || RFC8785(exact Stage1A expected-inventory row)
)
ordered_subject_universe_sha256 = SHA256(
  UTF8("FFDB-UNIVERSE-V1" + NUL)
  || concat(167 static_subject_projection digest bytes)
)
```

本冻结输入的 exact `ordered_subject_universe_sha256` 为
`ed8666f3c437dd83b97eae1e7189a502218e7e9d49e3831b444618c224e4b3c8`。这使原Stage1A中没有自带
`static_row_sha256`的 root/endpoint/relationship 也得到唯一静态projection；不得填dummy hash。

`EPB-HYP-EVO` 必须保持 `NOT_AUTHORIZED__UNBOUND_BLOCKING`。以下五个 adapters 同样是 absorbing
`NOT_AUTHORIZED__UNBOUND_BLOCKING`：

```text
ADP_DIAGNOSTIC_SIDECAR_CAPABILITY
ADP_CURRENT_EVO_SUPERSET
ADP_STEP56_EXECUTION_GATE
ADP_STEP56_RESULT_ACTION_READBACK
ADP_STEP56_BRANCH_COMPARISON_ACTION_READBACK
```

collector、issuer 或 verifier 不得自行做 N/A、缩域、删除 absent row 或生成 dummy binding。

### 6.1 Closed schema bundle

本合同的结构规范不是上述 prose 列表，而是同 packet 的：

```text
factorforge-epistemic-host-readback-closed-schema-bundle-v1.json
```

它使用 JSON Schema Draft 2020-12，闭合41个 compiler roots：33个 routed artifact roots、5个 preprofile
roots、2个 accepted-L0 specialized roots，以及1个 authority/profile-bound dynamic meta-root。每个 root 的
exact property names、required fields、type、cardinality、`additionalProperties=false` 和 closed `oneOf` 由
标准 JSON Schema validator 校验；bundle 顶层 `x-factorforge-*` semantic contracts 则必须由 accepted-L0
pin 的 noncaller semantic/preflight validator 强制执行，不能因标准 validator 忽略 extension keyword 而跳过。
旧的16类 public artifact 分组（8 dependency/control + 2 external prerequisite + 6 runtime chain）只保留为
legacy partition，不是 route-reference root 或 compiler-root 计数口径。

关键闭包包括：

- `PRESENT_COMPLETE|ABSENT|PARTIAL|PROHIBITED|BLOCKED` 五个 observation evidence branches；
- `AUTHORITY|ROOT_ANCHOR|DELIVERY_ENDPOINT|REQUIRED_RELATIONSHIP|STORE|DEPLOYMENT_ROW|ADAPTER`
  七个 material subject families；
- `FILESYSTEM|OBJECT_STORE|DATABASE|SERVICE_ENDPOINT` 四个 physical-proof oneOf；
- exact 167 material rows、24 SoD closures、161 eligible + 6 prohibited partition；
- session challenge issuance、collector live readback、Host attestation 与 independent verification 四份独立
  phase-authorization refs；
- phase authorization 与 independence receipt 的 closed external schema；
- bootstrap pin set、trust/nonrevocation、subject requirements、proof applicability、protected namespace 与
  两类control-store records八类dependency/control schemas；
- challenge、两个 content-attested targets、两份 action receipts 与 effective snapshot 的无环 references。

24个SoD profiles是static gating definitions，不进入167个material Merkle leaves；其24个closures单独固定顺序
与hash，并被两个target content hash覆盖。任一SoD未`CLEARED`都阻止overall `BOUND_VERIFIED`。

schema bundle GO 仍不等于 validator 已实现或 field semantics 已由 Host 绑定；结构 validator 与 semantic
validator 的 code/config SHA、subject requirement registry、proof applicability manifest 均须在 challenge 中
exact pin，任一缺失保持 `UNBOUND_BLOCKING`。

### 6.2 Execution-owner、selector、field-provenance 与 conformance 闭包

冻结 bundle 要求以下闭包同时成立，但这些仍只是 design contract，不是已执行 receipt：

- compiler roots 固定为 `41 = 33 + 5 + 2 + 1`；当前 `$defs` lexical universe 为381，roots 0..39 的
  local-ref reachable closure 为258，差集123必须由root 40逐项闭合。count、ordered manifest、fragment
  hash、edge hash或exact-pointer DAG任一漂移、遗漏或成环均`BLOCKED`；
- T1 execution-owner policy固定11行：5个signing/content roles的principal/context/capability只能
  `E_EXACT_EXTERNAL`等于已验证signed trust-binding row；projector与5个non-signing protected subservices
  只能等于typed noncaller OS/HW rooted handle。owner tuple不得携带自由`source_id`、caller fallback、
  alternate owner branch或新的authority。measurement root只能签已解析E-equality，不能生成、规范化、选择或
  修改owner identity，不能选择role/phase/grant/policy、授权execution或取得canonical identity/experience/
  memory/Skill/runtime/OOS authority；其scope delta状态固定为
  `DESIGN_ONLY__INDEPENDENT_OPERATING_AUTHORITY_APPROVAL_REQUIRED__UNBOUND_BLOCKING`，
  `r3_normative_role_universe_modified=false`且`deployment_rows_created=false`；
- primary selector registry固定6行，依次解析challenge、Host target、Host receipt、verification target、
  verifier receipt及snapshot `SELF`；每行必须绑定exact schema、field pointer、role、phase、service和
  measurement evidence。accepted-L0 static policy bundle冻结全部owner policy、selector、schema/profile pins、
  193个authority-comparison rows及3个validator-nonself rows；execution-attestation verifier handle V2必须
  对所有同名pin逐byte相等；
- root 29 `projector_sod_evidence_bundle` 的唯一normative来源是resolved field-provenance registry中的
  root-29 family/occurrence partition。每个reachable scalar occurrence必须绑定canonical ordered path AST、
  完整oneOf branch discriminator、terminal schema pointer、scalar type与cardinality，并且exact匹配一个
  closed enforcement binding。允许类别仅为`D/R/E/T/S`，`H=0`；material-owner equality使用typed
  material-E branch。zero/multiple/unclassified/ambiguous/unresolved、category/prose fallback或runtime具体
  array-index hardcode均`BLOCKED`。旧grouped catalog仅为`compiler_consumable=false`的解释材料；
- binding commitment依次进入family-row hash、family/binding manifests、occurrence-row hash、occurrence
  manifest、root-29 partition basis、registry content/artifact digest及registry ref；后置receipt、proof、
  snapshot或自身digest不得回入前置preimage；
- mandatory semantic obligations固定170项，minimum distinct conformance cases固定261项。Definition
  preflight必须在pinned noncaller engine下执行全部170项并验证261-case minimum closure；仅列出ID、
  manifest或`all_executed=true`自报不能替代执行证据。

## 7. 六个外部工件与内部证明无环链

```text
out-of-band signed challenge
  -> action-unsigned, content-provenance-signed sanitized readback target
  -> detached Host attestation receipt
  -> action-unsigned, content-provenance-signed independent verification target
  -> detached independent verifier receipt
  -> deterministic effective-status snapshot
```

上述仍是外部可见的六工件顺序；effective snapshot内部还必须闭合以下单向digest DAG：

```text
dual-Git definition bytes
  -> accepted-L0 static owner/projector-SoD policy bundle
  -> accepted-L0 profile/package/head
  -> execution-attestation verifier handle V2
  -> resolved trust-binding或OS/HW owner sources
  -> signed execution measurements
  -> SELF-precontent及5个external selector resolutions
  -> static 193+3 plan
  -> session-private protected projector-SoD bundle
  -> session-private resolver transcript V2（187 typed leaves，392 input-to-leaf mappings）
  -> public resolver-transcript ref V2
  -> semantic validation receipt
  -> receipt/bundle/transcript equality projection
  -> V3 projector-SoD proof
  -> 167 verification bases与Host row leaves
  -> 167 row-status bases
  -> whole-fold basis
  -> effective-snapshot content_sha256
```

187个private leaves严格为`6 primary + 5 auxiliary + 4 revocation + 2 external issuers + 167 material
subjects + 3 validator executions`；392个crosswalk rows严格为`193*2 + 3*2`。完整transcript及typed
leaves/native validation results只存在于session-private boundary。public ref是以下exact 25-field closed
metadata projection：

```text
schema_id, target_schema_id, transcript_profile_id, artifact_opaque_handle_sha256,
content_sha256, raw_bytes_sha256, projector_sod_evidence_bundle_ref,
accepted_l0_package_id, accepted_l0_profile_generation, accepted_l0_acceptance_head_sha256,
execution_owner_projector_sod_static_policy_bundle_content_sha256,
validator_execution_trio_basis_sha256, private_evidence_ref_count,
private_evidence_ref_manifest_sha256, resolved_leaf_count, resolved_leaf_manifest_sha256,
pairwise_input_occurrence_count, pairwise_input_to_leaf_manifest_sha256, resolver_profile_id,
retrieval_scope, storage_authority, private_evidence_bytes_disclosed,
stable_plaintext_identifier_disclosed, caller_supplied, ref_basis_sha256
```

其`retrieval_scope`固定为`SESSION_PRIVATE_PROJECTOR_SOD_VALIDATION_ONLY`，`storage_authority`固定为
`SESSION_PRIVATE_BYTES_ONLY_CANDIDATE__NONCANONICAL`；结构上不得包含private leaf arrays、native result
objects、crosswalk rows、`overall_resolution_verdict`或failure/unresolved detail counts。private transcript的
`overall_resolution_verdict=PASS`只是session-private resolution verdict；semantic validation receipt才是唯一
adjudicative PASS truth，receipt/bundle/transcript equality projection只重验并投影相等关系，不创建第二truth。

static policy/plan不得含runtime handle；bundle不得含transcript/receipt/proof/snapshot；private transcript不得
含receipt/proof/snapshot；public ref不得含private leaves/results；receipt不得含proof/snapshot；proof不得含
snapshot。任何successor digest进入predecessor preimage均`BLOCKED`。

### 7.1 Challenge

`factorforge_epistemic_host_readback_challenge_v1` 至少绑定：

- P0 manifest SHA、Stage1A commit 与 expected inventory content hash；
- frozen Stage1B0 packet manifest SHA 与 closed-schema-bundle SHA；
- ordered subject-universe hash；
- one-shot challenge ID、issued/expiry timestamps；
- protected out-of-band bootstrap pin-set ref，以及 distinct Host/verifier/external-authorization/
  external-isolation trust-manifest SHA/generations/anchors；
- allowed session issuer、collector、Host attestation issuer、verification-target author、verifier 与 deterministic
  effective-snapshot projector code/config hashes；
- expected readback-control-ledger parent head/generation 与 expected verification-registry parent
  head/generation，分别为 exact value 或 `ABSENT`；
- pre-session、out-of-band independence-receipt schema ID 与 SHA256；
- session-challenge-issuance、collector-live-readback、Host-attestation、independent-verification 四份 exact
  phase-authorization receipt refs；
- subject-requirement registry、physical-proof applicability manifest、protected-namespace manifest 与
  identity-commitment profile pins；
- output authority ceiling 全 false。

上述字段位于一个 closed `authorization_context` 中；四份 phase receipts 的 context 与 challenge copy 必须
byte-identical。`authorization_context_id` 是去除自身字段后的 domain-separated JCS digest。任一 receipt 只有
opaque scope hash、context 漂移，或 session issuer 自选 pin，都无效。

challenge 还必须包含 session issuer signing-time descendant nonrevocation snapshot ref、anchor→head closed
consistency path 与 `cutoff >= issued_at`。challenge 由 session issuer 签名，并由 session-issuance phase
authorization out-of-band pin；
Agent 不能自己签 challenge。target 必须同时绑定 challenge ID 与其
`completed_signed_artifact_sha256`，不能只绑定调用方提供的 ID。

challenge、readback target、Host receipt、verification target 与 verifier receipt 还必须分别记录 actual
role code/config SHA；effective snapshot 记录 projector actual code/config SHA。semantic validator逐角色/投影器
与 authorization context allowlist exact 比较，不能只证明“某个 approved binary 存在”。

### 7.2 Unsigned target

`factorforge_epistemic_host_readback_action_unsigned_content_attested_target_v1` 必须 exact bind challenge，并
原子包含：

- source repository logical ID、commit 与 deployment artifact manifest SHA；
- deployment-instance、installation 与 state-root opaque identity hashes；
- 3 个 root-anchor identity rows、2 endpoint rows 与 4 relationship rows；
- symlink、hardlink、bind-mount、object-prefix/table-alias closed scan verdict；
- 12 store 的 endpoint hash、store ID、generation/head、manifest SHA、schema、validator 和 CAS rows；
- 33 principal、67 event-purpose、1 external-trust deployment rows及24个SoD closures；
- 40 adapter native target/receipt/consumer rows；
- exact 167-row ordered manifest hash、domain-separated Merkle root 与 atomic cohort ID；
- distinct Host/verifier trust-manifest hashes、五个 purpose-specific key IDs、pre-session nonrevocation anchor
  heads 与 revocation temporal-policy hashes；
- readback window、collector code/config hash、sanitization audit 与 authority ceiling。

target 包含 collector 的 content-author preimage hash、content-provenance signature、signing-time descendant
nonrevocation head及从pre-session anchor到该head的append-only consistency-proof hash；不含任何
control-action signature、future receipt/verifier reference、private locator、raw identity component、
public/private key bytes或payload。target 内出现 `BOUND_VERIFIED` 或其他 effective-authority assertion 必须
直接拒绝；content signature 只证明 bytes provenance，effective status 只能由完整 verification chain 派生。

### 7.3 Host attestation receipt

`factorforge_epistemic_host_readback_attestation_receipt_v1` 只能 one-way bind：

```text
challenge ID/hash
+ completed signed challenge digest
+ action-unsigned content-attested target content hash
+ atomic cohort ID
+ source/deployment identity hash
+ Host trust manifest SHA/generation
+ pre-session Host nonrevocation anchor head
+ Host issuer signing-time descendant head and consistency-proof hash
+ readback window
+ replay/retention/expiry policy hashes
+ issuer principal/context/capability/key ID
```

签名前，external deployment-control ledger 必须先把 expected parent 以 CAS 变成只绑定
challenge+target+intended-attestation 的 reservation。Host receipt exact bind reservation ID/generation/head、
reservation receipt hash 与 read-set hash，但结构上禁止 finalization head/receipt。签名完成后，ledger 才把
该 reservation finalize 到 exact `completed_signed_artifact_sha256`；后续 verification target 必须绑定
completed digest + finalization receipt ref。该 control ledger 必须位于所有被证明 roots 之外；否则形成
bootstrap cycle。receipt不得回指后置finalization，target不得回指receipt，任一环都拒绝。

### 7.4 Verification target and receipt

`factorforge_epistemic_host_binding_action_unsigned_content_attested_verification_target_v1` 必须由独立
verification-target author 从
challenge、target、Host receipt、两个 out-of-band trust pins 和 live non-mutating readback 独立复算。
它记录每行 requirement verdict、SoD、relationship、freshness、replay、source/deployment 和 sanitization
verdict，但只能计算 pre-verifier disposition：eligible row最多为
`ELIGIBLE_REQUIREMENTS_SATISFIED_PENDING_VERIFIER`，overall最多为
`ALL_ELIGIBLE_REQUIREMENTS_SATISFIED_PENDING_VERIFIER`。该target结构上禁止`BOUND_VERIFIED`，因为未来
verifier PASS/signature尚不存在。它必须绑定 Host `receipt_id`、含 signature 的
`completed_signed_artifact_sha256`及external finalization ref，并携带verification-target author的
content-provenance signature与signing-time descendant nonrevocation proof。

`factorforge_epistemic_host_binding_verification_receipt_v1` 由 independent verifier detached-sign 已冻结的
verification target，并绑定 Host receipt ID/hash、verification-target author provenance、verifier
code/config hash、independence receipt、独立 verifier trust generation/nonrevocation head，以及 external
verification registry 的 pre-sign reservation。它不能只验证 Host signature；必须绑定独立
physical/trust/adapter readback。receipt签完后registry再external-finalize reservation到exact completed digest；
receipt本体结构上禁止finalization result，也不自行写最终effective status。

verifier receipt 中的 nonrevocation head 必须是对应 pre-session verifier anchor 的 signing-time descendant，
并绑定 exact completed signed nonrevocation-snapshot ref、closed append-only consistency path/tree sizes、cutoff
与 revocation temporal-policy hash。

其中“Host receipt hash”和“verifier receipt hash”均指第8节的
`completed_signed_artifact_sha256`，覆盖 exact signature bytes；`receipt_id` 只标识 unsigned semantic
preimage，不能单独作为后续 chain reference。

### 7.5 Effective snapshot

`factorforge_epistemic_host_binding_effective_snapshot_v1` 是 challenge、两个 content-attested targets 和
两份 detached receipts 的 deterministic projection。它必须绑定 challenge ID+completed digest、两个 target
content SHA，以及两份 receipt 各自的 receipt ID+completed digest+external finalization ref。只有 verifier
receipt 为 `PASS`、signature/nonrevocation有效且verification-registry finalization闭合后，此snapshot才是
`BOUND_VERIFIED`首次可出现的工件；没有签发next-gate/runtime authority，只允许external reviewer判断
binding证据是否闭合。其 `projector_execution_identity` 必须与 authorization context 中 externally allowed
projector code/config exact相等；projector 自报 hash、fallback binary 或未 pin config 均不能发布 snapshot。

## 8. Canonicalization、hash 与 signature

本候选冻结 RFC 8785 JSON Canonicalization Scheme（JCS），并要求 I-JSON：UTF-8、duplicate key reject、
nonfinite reject、lone surrogate reject、closed shape 和 exact type。stored JSON bytes 必须恰为 JCS bytes
加一个 LF。实现前必须有 cross-runtime canonicalization vectors；不能用“stable JSON”、语言默认 float
serialization 或普通 `sort_keys` 替代。

content-provenance-signed target 的计算顺序固定为：

```text
content_author_preimage_sha256 = SHA256(
  UTF8(schema_id + NUL + "content-author-preimage" + NUL)
  || RFC8785(target without content_author_preimage_sha256,
             content_author_signature,
             content_sha256)
)
content_author_signature_input =
  UTF8(schema_id + NUL + "content-author-signature" + NUL)
  || digest_bytes(content_author_preimage_sha256)
content_sha256 = SHA256(
  UTF8(schema_id + NUL)
  || RFC8785(target without content_sha256)
)
```

因此最终 `content_sha256` 覆盖 author-preimage hash 与 exact author signature；issuer/verifier 无法在不知道
author content key 时重写 target。content-provenance signature 不产生任何 action authority。

普通内容对象：

```text
content_sha256 = SHA256(
  UTF8(schema_id + NUL)
  || RFC8785(object without content_sha256)
)
```

该规则同样适用于 bootstrap pin set、trust manifest、subject requirement registry、proof applicability
manifest、protected namespace manifest、control-store reservation/finalization records 与 deterministic effective
snapshot；`content_sha256` 永远不参与自身 preimage。

authorization context 使用独立 domain：

```text
authorization_context_id = SHA256(
  UTF8("factorforge-epistemic-authorization-context-v1" + NUL)
  || RFC8785(authorization_context without authorization_context_id)
)
```

detached receipt：

```text
receipt_id = SHA256(
  UTF8(schema_id + NUL + "receipt-id" + NUL)
  || RFC8785(receipt without receipt_id and signature)
)
signature_input = UTF8(schema_id + NUL + "signature" + NUL)
  || RFC8785(receipt including receipt_id but excluding signature)
```

signed challenge 使用独立 domain，避免与 receipt 互换：

```text
challenge_signature_input = UTF8(schema_id + NUL + "challenge-signature" + NUL)
  || RFC8785(challenge excluding signature)
```

signed receipt 结构上禁止 `content_sha256` 自哈希字段；完整 signed file SHA 只放在 outer packet manifest。
同时定义无环的 completed signed-artifact digest：

```text
completed_signed_artifact_sha256 = SHA256(
  UTF8(schema_id + NUL + "completed-signed-artifact" + NUL)
  || RFC8785(complete signed artifact)
)
```

该 digest 不写回被哈希 artifact，只能出现在后续工件的 exact reference 中。signed receipt 只能绑定预先
存在的reservation，不能包含后置CAS finalization result。后续对 content target 必须
绑定 schema ID + artifact ID + `content_sha256`；对 receipt 必须绑定 schema ID + `receipt_id` +
`completed_signed_artifact_sha256`与external finalization receipt ref；outer stored-file SHA 仍只属于 packet manifest，与上述
semantic chain digest 不同。

target 不能包含 future receipt/verifier reference；detached receipt 则必须 exact reference 已先冻结的 target。
任何 hash/signature cycle、语义相等但 bytes 不同、unknown field
或 int/bool 混淆都 fail closed。

167-row ordered manifest 与 Merkle proof 使用：

```text
leaf_i = SHA256(UTF8("FFDB-LEAF-V1" + NUL) || RFC8785(row_i))
rows_hash = SHA256(UTF8("FFDB-ROWS-V1" + NUL) || concat(leaf_0 ... leaf_166))
node = SHA256(UTF8("FFDB-NODE-V1" + NUL) || left_digest_bytes || right_digest_bytes)
```

每层奇数个 node 时，最后一个 node 原样提升，不复制、不重哈希；array order 由第6节绑定的 Stage1A
expected-inventory family/within-family order 决定，不能按 runtime discovery order、path 或 mtime 排序。

## 9. Atomic snapshot、freshness 与 replay

一个 target 必须只绑定：

```text
one source deployment identity
+ one installation identity hash
+ one Host trust-manifest SHA/generation
+ one independent-verifier trust-manifest SHA/generation
+ one external-authorization trust-manifest SHA/generation
+ one external-isolation trust-manifest SHA/generation
+ one pre-session nonrevocation anchor head per all four trust domains
+ one policy generation
+ one readback window
+ one atomic cohort ID
```

每个 subject row 都必须绑定同一 cohort。不同 commit、generation、trust manifest、policy 或 observation
window 的拼接 snapshot 无效。nonrevocation 不要求错误地复用一个静态 head：authorization context 绑定每个
trust domain 的 pre-session anchor；每个签名者必须绑定 exact completed nonrevocation-snapshot bytes、一个
signing-time strict-descendant head、anchor→head 的 closed append-only consistency path/tree sizes、
`cutoff >= signed issued_at`，以及禁止 backdating 的 revocation temporal-policy hash。任何 snapshot bytes或
path不可验证、head 不可证明为对应 anchor 的合法 descendant、cutoff 太早或 policy generation 漂移均无效。

unknown/unreadable 不等于 absent。collector 不能因 permission error、missing validator、timeout 或 backend
不支持而填 `OBSERVED_ABSENT`；必须 `OBSERVATION_BLOCKED`，effective status 保持 unbound。

challenge 必须 single-use、限时、绑定 expected prior head。identical replay 只允许返回同一
reservation/signed-receipt/finalization chain；不同 target 使用同一 challenge、stale parent、并行reservation、
未finalize receipt、过期 receipt 或 revoked key 都拒绝。具体 reserve/finalize 实现属于后续 gate，本合同不
创建 ledger。

一旦发布新的 unverified generation，consumer 不得 fallback 到旧 `BOUND_VERIFIED` generation。binding
只对 exact deployment instance、generation、cutoff 和 policy 有效，不是永久授权。

## 10. Physical identity 与 relationship proof

Agent-facing packet 只能含 session/purpose-separated opaque identity commitment。raw `st_dev`、inode、mount ID、namespace、
object prefix、bucket、database/table locator 或 private path 禁止跨 boundary。

commitment profile 固定为：

```text
profile_id = FFDB_OPAQUE_ID_HMAC_SHA256_HKDF_SESSION_V1
K_session_purpose = HKDF-SHA256(
  K_identity_commitment_master,
  salt = UTF8(challenge_id),
  info = UTF8(profile_id + NUL + purpose_id)
)
opaque_identity_hash = HMAC-SHA256(
  K_session_purpose,
  RFC8785(private_identity_tuple)
)
```

challenge 必须 pin master key ID、private-tuple canonicalizer SHA 与 closed purpose-registry SHA；master key
只能由 collector 与 verification-target author 的受保护 context 调用，不能出现在任何 packet。相同 session、
purpose 与 private tuple 必须得到相同 commitment；不同 session 或 purpose 不得可链接。没有该等价律时只
能 `OBSERVATION_BLOCKED`，不能输出 caller-chosen hash。

Host collector 与 verification-target author 内部必须分别复算：

| Left | Right | Required |
|---|---|---|
| canonical-memory root | epistemic-transaction root | `DISJOINT_SIBLING` |
| request endpoint | response endpoint | `DISJOINT_SIBLING` |
| delivery root | canonical-memory root | `DISJOINT_SUBTREE` |
| delivery root | epistemic-transaction root | `DISJOINT_SUBTREE` |

每行还必须证明不存在：

```text
ALIAS
SAME_ROOT
ANCESTOR
DESCENDANT
SYMLINK_EQUIVALENT
HARDLINK_EQUIVALENT
BIND_MOUNT_EQUIVALENT
OBJECT_PREFIX_OR_TABLE_OVERLAP
```

字符串不同、`Path.resolve()`、同一 owner、不同 logical ID 或普通 ancestry check 都不是完整证明。challenge
必须 pin exact physical-proof applicability manifest；不同 backend 只能选择 schema bundle 的 closed proof
oneOf。collector/verifier不得动态判 N/A；unsupported backend 只能`OBSERVATION_BLOCKED`。

collision set 必须由 session 前存在的 closed
`factorforge_epistemic_protected_namespace_manifest_v1` 给出 exact generation、entry count 与 manifest SHA。
它至少覆盖现有 researcher-memory EVO sidecars、historical episode roots、trust root、jobs/public/attestation
roots；不得用开放的“其他 namespace”文字动态增删。collector 与 verification-target author 分别对同一
exact manifest 全量扫描；manifest 缺失、过期或无法证明闭包时只能 block。

## 11. Row effective-status law

Host target 只记录 observation；Host attestation 只证明 target provenance。两者都不能签发
`BOUND_VERIFIED`。

一个 eligible row 只有同时满足以下条件才可由 verifier-receipt finalize之后的 deterministic effective
snapshot projection 计算为
`BOUND_VERIFIED`：

1. exact P0 subject identity；
2. complete sanitized observation；
3. same atomic cohort；
4. exact source commit → deployment artifact binding；
5. valid protected bootstrap pin set 与四个 distinct out-of-band trust pins；
6. valid Host detached attestation；
7. valid pre-session anchors，以及四份 phase authorization、independence receipt、session、collector-content、
   Host issuer、verification-author-content、verifier 的每个签名各自 exact nonrevocation-snapshot ref、
   descendant head、closed consistency path 与 signing-time cutoff；
8. independent verifier PASS 与 detached signature；
9. row-specific required fields全部闭合；
10. effective-snapshot projector actual code/config 与 authorization context allowlist exact match；
11. no SoD、root relationship、freshness、replay或sanitization violation。

任一缺失、unknown、hash-only claim、unsigned self-declaration 或 prose assertion 都保持
`UNBOUND_BLOCKING` 或原 `PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`。`NOT_AUTHORIZED` 是 absorbing state。

## 12. Whole-snapshot aggregation

全部167个material subjects必须逐行fold：161个eligible = 5 authorities + 3 roots + 2 endpoints +
4 relationships + 12 stores + 100 deployment rows + 35 adapters；6个prohibited = 1 deployment row +
5 adapters，必须保持 `NOT_AUTHORIZED__UNBOUND_BLOCKING`。24个SoD closures在fold前作为独立gating
vector校验，不计入167。

聚合 precedence 固定为：

1. 任一 prohibited subject 被实际化、出现 capability/receipt 或 authority ceiling uplift：
   `NOT_AUTHORIZED__UNBOUND_BLOCKING`，且不得发布 consumable snapshot；
2. 任一 material subject absent、unknown、unreadable、过期、`OBSERVATION_BLOCKED` 或 exact status 为
   `UNBOUND_BLOCKING`：`UNBOUND_BLOCKING`；
3. 无第二类 ordinary-unbound subject、但至少一个eligible row仍为exact frozen partial-native seam：
   `PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`；
4. 所有 eligible authorities/roots/endpoints/relationships/stores/deployment rows/adapters 均为 `BOUND_VERIFIED`，且
   所有 prohibited subjects 有合法 negative proof：`BOUND_VERIFIED`。

第四种情形才可投影：

```text
overall_effective_status = BOUND_VERIFIED
```

只要仍有任一 material unbound row，部分 row success 的 overall status 都固定 `UNBOUND_BLOCKING`。不得用
coverage ratio、majority、critical subset、current-native-only 或 dummy row 放行。

即使 overall `BOUND_VERIFIED`，以下字段仍全部为 false：

```text
runtime_authority
rag_authority
skill_authority
canonical_write_authority
oos_authority
next_gate_authority
```

下一门仍需 external reviewer 单独裁决。

## 13. Sanitized output closed allowlist

允许：

- frozen logical ID、schema ID/version 与 closed enum；
- SHA-256 digest、opaque key ID、nonnegative generation/count；
- UTC timestamp 与 bounded validity interval；
- closed boolean verdict；
- detached control-action signature 与 embedded content-provenance signature 的 algorithm/value。

禁止：

- absolute/private path、private URI 或 Agent-resolvable locator；
- installation identity plaintext/seed；
- raw device/inode/mount/object-prefix/table-locator components；
- private key、credential、secret 或 token；
- public key bytes（Agent-facing packet 采用 manifest hash + key ID/public-key digest）；
- canonical memory/lesson/review/outcome/episode payload；
- OOS locator/token/carrier/window/content 或 overlap facts；
- factor metrics/verdict/promotion/decision；
- prompt、free prose、reasoning trace/chain-of-thought；
- exception text、unknown field、input value 或未验证 hash 回显。

signature value 不是 secret；control-action signature 只能出现在 closed challenge/receipt field，
content-provenance signature 只能出现在两个 closed target author-signature field。

## 14. Current native seam disposition

本合同冻结以下 current observation，但不升级状态：

- Host memory authority/canonical root：`PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`；
- current EVO qualifier/event/external trust：`PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`；
- 5 个 current native adapters：`PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING`；
- 12 stores、2 endpoints、4 relationship proofs：`UNBOUND_BLOCKING`；
- 其余 absent principals/events/adapters：`UNBOUND_BLOCKING`；
- `EPB-HYP-EVO` 与5个 future adapters：`NOT_AUTHORIZED__UNBOUND_BLOCKING`。

现有 trust loader 未来可用于 Host-side readback，但其 public manifest 含 installation plaintext 与 public key
bytes，不能原样投影。现有 memory manifest 的 store ID/generation/hash可作为 collector input，但 collector
不得读 canonical records/reviews/outcomes payload，也不得调用会 recovery 的 validator。

## 15. Implementation gates

Stage1B-0 review GO 之前禁止：

- collector、signer、challenge ledger 或 independent verifier implementation；
- live Host root/store/trust discovery；
- key generation、trust migration 或 generic key repurposing；
- signature generation、deployment receipt 或 `BOUND_VERIFIED` 输出；
- P1A fixture materialization/execution；
- RAG、Step/Ultimate Skill、runtime、shadow、canonical memory 或 OOS mutation；
- 不得把381/258/123静态计数、root-29 `CLOSED_PASS` shape、170/261 contract或manifest自报解释为
  runtime validation完成；
- accepted-L0 package/profile/head、verifier handle V2、11个actual owner measurements、private transcript
  resolver、semantic/preflight validator code/config及全部mandatory execution receipts未被Host实际绑定前，
  deployment status继续为`UNBOUND_BLOCKING`；
- owner-equality scope delta的独立operating-authority approval receipt未签发前，measurement root不得执行该
  scope refinement，也不得据此创建deployment row或扩大R3 role universe。

Stage1B-0 GO 只允许 Host 选择：提供已存在且purpose-specific的native control-plane contract，或单独授权
Stage1B-1 collector implementation。Stage1B-1 仍不能自动授权 Stage1B-2 signing。

## 16. Reviewer blockers

以下任一项应裁决 `STAGE1B0_META_DESIGN_REVISE`：

1. control-plane authority 获得 semantic/runtime/canonical/OOS authority；
2. `FF_SNAPSHOT_ISSUER_V1` 或任一被绑定 subject 参与 bootstrap；
3. trust manifest 由 response 自我 pin；
4. generic `host_admission` key 被默认当作 purpose-specific deployment key；
5. session issuer、collector、Host issuer、verification-target author、verifier SoD 未闭合；
6. content-author或action signature input、completed signed-artifact digest、self-hash exclusion不唯一；
7. target 含 future receipt/verifier backreference、receipt 不 exact bind 先前 target，或 signed receipt 含自哈希；
8. mixed commit/generation/trust/policy snapshot 可被接受；
9. unknown/permission error被当作absent；
10. partial row、coverage threshold 或 critical subset 可把 overall 升级；
11. `NOT_AUTHORIZED` row/adapter 可被 readback 升级；
12. output 暴露 private locator、identity component、key material、payload、OOS 或 factor outcome；
13. meta-contract GO 被解释为 collector、signing、runtime 或下一 gate authority。
14. bootstrap pin set 可从 request/packet 注入，四份 phase receipts 不共享 exact authorization context，或
    session issuer 可自选/缩小 trust、scope、proof、policy、code/config 或 expected-head bindings；
15. nonrevocation 只有裸 hash、没有 exact signed snapshot ref与closed consistency path；
16. effective snapshot projector code/config 未被 external authorization context pin 或可自报；
17. subject requirement、proof applicability、protected namespace、reservation/finalization任一dependency仍只用
    prose/hash占位而没有closed schema或逐字段相等律；
18. 41-root、381/258/123 definition closure、ordered manifests或exact-pointer DAG不一致；
19. 任一T1 owner、6-row selector或accepted-L0 static-policy/handle pin可由caller、ambient state、free source ID
    或alternate branch替代；
20. root-29 occurrence缺canonical path/branch/cardinality/exact enforcement binding，出现H、zero/multiple
    match、material-E缺失、category fallback或commitment propagation断裂；
21. private 187-leaf/392-crosswalk transcript泄漏到public ref，或public ref被当作无需解析private transcript的
    独立PASS证据；
22. 170 mandatory obligations未全部执行、261-case minimum未闭合，或design-only schema/manifest被解释为
    implementation/deployment evidence；
23. owner-equality scope delta被视为已批准，measurement root可生成/选择owner、授权execution、创建deployment
    row、扩展R3 role universe，或其独立operating-authority approval receipt仍为空却继续执行。
