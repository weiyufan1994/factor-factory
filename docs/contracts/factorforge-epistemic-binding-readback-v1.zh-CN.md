# Factor Forge Epistemic Binding Stage1A-PREP 合同 V1

## 1. 身份、用途与权限上限

本合同定义 Epistemic Graph V2 部署绑定工作的第一个可实现子阶段：
`STAGE1A_PREP_OFFLINE_BASELINE`。

它只完成三件事：

1. 从冻结 P0 packet 重建 closed expected inventory；
2. 生成全部保持 `UNBOUND | PROHIBITED_NOT_AUTHORIZED` 的 blank readback template；
3. 离线验证这两个对象的 bytes、闭包和“不具备部署权限”这一事实。

本阶段不是 Host deployment readback，不观察真实 root、store、principal、key、trust、adapter
或 endpoint，也不签发任何证明。它没有 runtime、Skill、RAG、canonical memory、Council、OOS、
training、shadow、migration、repair 或 promotion authority。

合法终局只有：

```text
VALID_STAGE1A_PREP__INCOMPLETE__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING
BLOCK_STAGE1A_PREP_INVALID
```

第一个终局只表示“离线准备包有效”；不得解释为 `BOUND_VERIFIED`、`DEPLOYED`、`READY`、
`GO_RUNTIME`、Host readback 完成或下一阶段自动获批。

## 2. 冻结输入基线

所有 builder 和 validator 必须绑定以下 exact identity：

| 对象 | SHA-256 / identity | 作用 |
|---|---|---|
| P0 `packet_manifest.json` | `58c3585881f52c4ed60c4e7fb582e9b30acf0063433c12363915d54f0b985c4f` | 唯一 packet identity |
| P0 packet ID | `FACTORFORGE_EPISTEMIC_GRAPH_V2_P0_BINDING_REVIEW_20260822_R2` | 唯一 packet namespace |
| P0 artifacts | manifest 中 11/11 exact bytes 与 SHA-256 | closed design source |
| P0 directory | manifest + 11 artifacts，恰好 12 个普通、单链接、非 symlink 文件 | directory closure |
| native-seam baseline commit | `dc6f55ab6ea1f9dc32518e3af02df4a9e5d423ee` | 当前 Host seam 的只读设计基线 |

该 commit 在本阶段仅通过 exact P0 artifacts 被传递绑定；Stage1A-PREP 不读取 live checkout、
不声明当前部署仍等于该 commit。source checkout 与 deployment instance 的真实绑定属于下一 gate。

冻结 P0 verdict 为：

```text
P0_BINDING_DESIGN_GO__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING
```

任一 manifest SHA、packet ID、artifact bytes/hash/membership 或目录闭包不匹配时必须 fail closed；
不得 fallback 到相邻 packet、旧版本、repo 副本、调用方列表或近似 schema。

loader 必须以逐级 `O_NOFOLLOW` 打开并全程固定 packet directory fd/dev/inode；所有 list、stat 与
read 都必须 at-relative，entry open 必须带 `O_NONBLOCK`，从而使 regular file 被并发替换为 FIFO
时立即拒绝而不是等待 writer。第一次 closure scan 后读取全部 bytes，再 second-read manifest 与 11 个
artifacts，最后执行 12-file closure snapshot 与 directory dev/inode/mtime/ctime 检查；读取期间新增、
删除、临时隐藏、替换或改变任一 entry 都必须拒绝。

## 3. 三对象分层

后续部署链路必须区分：

```text
binding_decision != deployment_observation != effective_status
```

- `binding_decision`：冻结 P0 中的 logical candidate；
- `deployment_observation`：未来由 Host 在授权窗口内只读观察的部署事实；
- `effective_status`：未来由独立 validator 根据 proof 计算的状态。

Stage1A-PREP 只携带第一类对象，并为第二类对象生成 blank slot；它既不产生
`deployment_observation`，也不计算部署层 `effective_status`。blank slot 不得被调用方声明、默认值、
generic signature 或 operator assertion 升级。

## 4. Closed universe 与精确基数

expected inventory 必须从冻结 `02_authority_principal_store_binding_registry.json` 和
`03_native_adapter_consumer_registry.json` bytes 重建下列全集：

| 对象族 | 精确数量 |
|---|---:|
| authority boundaries | 5 |
| SoD profiles | 24 |
| root anchors | 3 |
| root-anchor relationships | 3 |
| delivery endpoints | 2 |
| request/response endpoint relationship | 1 |
| required relationships total | 4 |
| logical stores | 12 |
| principal deployment rows | 33 |
| typed event-purpose deployment rows | 67 |
| external trust deployment rows | 1 |
| deployment rows total | 101 |
| native adapters | 40 |
| discriminated adapter locators | 38 |
| singleton unique-schema locators | 2 |

### 4.1 SoD closure

24 个 SoD profile 必须显式 materialize，至少保留：

```text
profile_id
constraint_kind
dynamic_closure_ref
static_row_sha256
```

67 个 event row 的 `sod_profile_ref` 必须全部存在、exact resolve，且引用全集必须与 24 个 profile
全集闭合。不能只把 SoD 隐藏在 event row hash 中。

### 4.2 101 个 deployment pointers

冻结 registry 中 101 个 `deployment_row` 必须全部为 `null`。每个 expected row 必须携带：

```text
source_registry_artifact = 02_authority_principal_store_binding_registry.json
deployment_row_json_pointer
```

pointer 只能为以下三族、使用冻结 source array index：

```text
/principal_requirements/{i}/deployment_row
/principal_event_purpose_bindings/{i}/deployment_row
/external_trust_domain_bindings/{i}/deployment_row
```

101 个 pointer 必须唯一、一一对应、全覆盖；排序后的 output row 不得改变原始 pointer index。

### 4.3 Adapter locator closure

40 个 adapter 必须保持冻结的 closed oneOf：

- 38 个 discriminated locators 必须携带冻结 discriminator；
- 2 个 singleton unique-schema locators 结构上不得出现 discriminator；
- 不得发明 token、合并 locator 或把 `NOT_AUTHORIZED` 改成可绑定。

## 5. Root、endpoint 与关系闭包

三个 root anchor ID 必须逐字等于：

```text
FF_HOST_MEMORY_AUTHORITY_CURRENT.CANONICAL_RESEARCHER_MEMORY_STORE_ROOT
FF_HOST_MEMORY_AUTHORITY_CURRENT.EPISTEMIC_TRANSACTION_NAMESPACE_ROOT
FF_HOST_AGENT_DELIVERY_AUTHORITY_CURRENT.HOST_PRIVATE_DELIVERY_STATE_ROOT
```

两个 delivery endpoint 必须逐字段匹配冻结 root、relative locator、authority 和 schema：

```text
FF_RAG_OPAQUE_REQUEST_DELIVERY_LEDGER_CURRENT
  epistemic-graph-v2/v1/delivery-ledgers/request

FF_RAG_OPAQUE_RESPONSE_DELIVERY_LEDGER_CURRENT
  epistemic-graph-v2/v1/delivery-ledgers/response
```

四个 required relationship 必须完整保留：

| Left | Right | Required |
|---|---|---|
| canonical memory root | epistemic transaction root | `DISJOINT_SIBLING` |
| request endpoint | response endpoint | `DISJOINT_SIBLING` |
| delivery root | canonical memory root | `DISJOINT_SUBTREE` |
| delivery root | epistemic transaction root | `DISJOINT_SUBTREE` |

每一行同时携带冻结的 forbidden physical relationship 全集：

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

Stage1A-PREP 只冻结这些待证明关系，不观察或证明物理关系。

## 6. 三类输出对象

### 6.1 Expected inventory

schema ID：

```text
factorforge_epistemic_binding_expected_inventory_v1
```

它必须包含 exact baseline、artifact inventory、精确 counts、authorities、SoD、roots、四个
relationships、endpoints、12 stores、101 deployment rows、40 adapters 和全部为 `false` 的
authority ceiling。

### 6.2 Blank readback template

schema ID：

```text
factorforge_epistemic_binding_blank_readback_v1
```

它必须 exact bind inventory content hash，保留相同 logical universe，并固定：

```text
readback_mode = BLANK_OFFLINE_TEMPLATE_ONLY
readback_state in {UNBOUND, PROHIBITED_NOT_AUTHORIZED}
```

只有冻结 baseline 为 `NOT_AUTHORIZED__UNBOUND_BLOCKING` 的 row 可投影为
`PROHIBITED_NOT_AUTHORIZED`；其余全部为 `UNBOUND`。不得出现任何 positive deployment state。

公开 blank-template builder 只接受 exact P0 packet root，并在内部重建 expected inventory；不得接受
调用方提供的 inventory object。内部 helper 即使收到自哈希有效的对象，也必须结构性验证
`authority_ceiling` exact key set 且全部为 `false`。

### 6.3 Offline validation receipt

schema ID：

```text
factorforge_epistemic_binding_offline_validation_receipt_v1
```

receipt 必须有自身 content hash，并固定：

```text
runtime_authority = false
host_readback_authority = false
binding_authority = false
publication_authority = false
consumption_authority = false
signature_generation_authority = false
```

builder 成功时必须直接返回同一个 staged validator receipt；不得另造无 schema、无 content hash、
却带 `validation_status` 的第四类 summary。

失败 receipt 不得回显未验证的 content hash、未知 key、输入 value、path、secret 或异常正文；只允许
closed public reason code。无法安全投影的原因统一变为 `REDACTED_STAGE1A_PREP_REJECTION`。

## 7. Canonical bytes 与 content hash

两个 JSON artifact 必须同时满足：

1. duplicate key、非有限数、过深或过大 JSON 被拒绝；
2. file bytes 为 UTF-8、`sort_keys=true`、`indent=2`、`ensure_ascii=false`、末尾单个 LF；
3. validator 必须比较 raw bytes 与 canonical serialization bytes，语义等价但 whitespace/order 不同也拒绝；
4. `content_sha256` 对移除自身后的 compact canonical JSON 投影计算，使用
   `sort_keys=true`、`separators=(",", ":")`、`allow_nan=false`、UTF-8；
5. inventory 与 template 必须互相通过 exact content hash binding。

## 8. Sanitized-output law

Stage1A-PREP 输出是 allowlist-generated closed object。任何层级均不得出现：

```text
absolute/private path or private URI
Windows drive path or UNC path
credential, password, API/access/refresh token
private/public key bytes or signature
installation identity plaintext
canonical memory, lesson, review or outcome payload
OOS token, carrier, locator, window or content
factor metric, verdict, promotion result
free prose, prompt, reasoning trace or chain-of-thought
```

唯一允许以 `/` 开头的 value 是结构字段 `deployment_row_json_pointer`，且必须通过 canonical
JSON-pointer pattern。错误文本不得包含输入字段名或输入值。

## 9. Offline builder 与 publication law

builder 只接受两个显式 absolute arguments：exact P0 packet root 与一个尚不存在的 output root。
它不得读取环境变量、默认 Host state、live service、canonical memory、private config、OOS 或网络。

output parent 必须由调用方预先提供，且为当前 OS owner 持有、POSIX group/other 权限均为零的
owner-private directory。builder 必须以逐级 `O_NOFOLLOW` 的 parent dirfd 固定其 dev/inode；output
parent 不得等于或位于冻结 P0 packet 或当前 implementation repo 子树内。Host state、Skills、
canonical memory、OOS 与其他 protected roots 仍由调用方的 authority policy 明确排除。

本阶段的机械 threat model 只覆盖 owner-private、无 hostile same-UID concurrent writer 的 parent。
mode `0700` 不等价于独立 OS principal；若存在不受信的同 UID writer，必须 fail closed，并在后续
部署阶段改用独立 principal/受保护 parent。本合同不得声称当前协议能抵抗恶意 same-UID parent mutation。

publication 必须：

1. 在 pinned private parent dirfd 下排他建立 mode `0700` 的随机 staging directory；
2. create-only 写入 inventory 与 template；
3. 在 staging 内完成同一个 offline validator；
4. 通过 pinned staging dirfd 验证目录恰好两个 regular、single-link 文件，bytes 与 expected canonical
   bytes 完全相等，并 fsync staging；
5. 只有合法 `VALID_STAGE1A_PREP...` receipt 才可使用 Darwin
   `renameatx_np(RENAME_EXCL|RENAME_NOFOLLOW_ANY|RENAME_RESOLVE_BENEATH)` 或 Linux
   `renameat2(RENAME_NOREPLACE)` 发布整个 directory；不支持原生 no-replace 时 fail closed；
6. output root 已存在、是 symlink、在发布前出现、parent/staging identity 改变、目录出现第三个
   entry 或 staged validation 失败时，必须拒绝且不覆盖；成功后验证 final dev/inode 并 fsync parent；
7. 失败时禁止经 Path 遍历或清理 staging，以免 symlink substitution 删除无关文件。未发布 staging
   保留为不可消费 quarantine；offline validator 可以只对其中两个文件的 bytes/静态闭包给出
   `VALID_STAGE1A_PREP...`，但该 receipt 固定 `publication_authority=false`、
   `consumption_authority=false`，绝不证明 final output identity、成功发布或可消费性。Host、Agent 或人工
   消费者必须另证 create-only final output identity；quarantine 的后续处置须是另一个显式、
   identity-pinned 操作。

Stage1A-PREP 的输出 mutation authority 只覆盖调用方明确给出的新 output root；不覆盖 Host state、
repo contracts、Skills、memory store 或冻结 P0 packet。

## 10. Offline validator law

validator 只接受 exact P0 packet、inventory file 和 template file 三个显式 absolute path。它必须：

1. 重新复算完整 P0 manifest 与 directory closure；
2. 从冻结 bytes 重新生成 expected inventory/template；
3. 验证 closed top-level shape、canonical bytes、content hash 与 exact object equality；
4. 验证 24 SoD、67 refs、101 pointers、四个 relationships 与 40 locators；
5. 验证所有 readback state 仅为 `UNBOUND | PROHIBITED_NOT_AUTHORIZED`；
6. 验证至少存在一个 `UNBOUND`，且 authority ceiling 全部为 false；
7. 不查询 Host、不回调 builder、不使用 fallback；
8. CLI argument parser 的 error path 不得打印 usage、未知参数或调用方 value；parse failure 与任意
   非 `BaseException` 异常统一生成 fixed、content-hashed rejection receipt；
9. public `validate_stage1a_files` 自身也必须 total-return：包括非法非有限数、lone surrogate、FIFO、
   底层 I/O 或 canonical serialization failure 在内的任意普通异常，都只能变成 fixed、content-hashed
   `BLOCK_STAGE1A_PREP_INVALID`，不得裸抛或回显；
10. 最多返回 `VALID_STAGE1A_PREP__INCOMPLETE__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING`；该状态只证明显式
   输入文件的离线 bytes/静态闭包，固定没有 publication/consumption authority，不能证明这些路径来自
   成功发布的 final output root。

任一输入缺失、非 canonical、篡改、超限、未知、重复或无法安全读取时返回
`BLOCK_STAGE1A_PREP_INVALID`。

## 11. 明确未实现与下一 gate

本合同与当前代码明确没有实现：

- sanitized live Host deployment readback；
- 三个 root 的 physical identity、两个 endpoint identity 与四个 relationship proof；
- 12 个 store 的 generation/head/schema/validator/CAS observation；
- principal/context/capability/key/SoD/trust/revocation/nonrevocation binding；
- adapter content hash 与 deployment receipt；
- independent verifier receipt 或 purpose-specific signature；
- Source-First、Exploit/Explore `0..N` operating delta；
- P1A RAG、diagnosis、applicability ledger 或 negative fixtures；
- Ultimate/Step1-6 Skill integration。

下一阶段必须是单独授权、单独 manifest-bound 的 Host sanitized readback/binding 阶段。它可以消费
Host-private locator 和 trust information，但只能输出不可逆 sanitized identity/proof；不得复用本阶段
blank template 冒充 observation，不得因为本阶段测试通过而自行创建 root、ledger、key 或 service。

之后仍须依次通过：独立 physical/trust verification、Source-First 与 Exploit/Explore operating-delta
审批、P1A offline conformance、Skill integration review、shadow/runtime authorization。任一 gate 不得
自动推出下一 gate。

## 12. Stage1A-PREP 验收不变量

```text
exact P0 manifest and 11/11 artifact bytes verified
12-file regular non-symlink directory closure verified
5 authorities + 24 SoD + 3 roots + 2 endpoints + 4 relationships closed
12 stores + 33 principals + 67 events + 1 external trust row closed
101 deployment-row canonical JSON pointers unique and complete
40 adapter locators closed as 38 discriminated + 2 singleton
canonical JSON bytes and content hashes verified
no private path, secret, payload, OOS, free prose or error echo
all authority ceilings false
all blank states remain UNBOUND or PROHIBITED_NOT_AUTHORIZED
final status cannot exceed deployment remains unbound blocking
```

任何机械闭包、hash PASS 或测试通过都不得改变最后两条。
