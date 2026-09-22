# Stage1B-0 Host Readback Meta-Contract Review Checklist V1

## 1. Review identity 与边界

本 checklist 请求对以下 candidate bytes 做 manifest-bound、只读 design review：

```text
factorforge-epistemic-host-readback-stage1b0-packet-manifest-v1.json
factorforge-epistemic-host-readback-meta-contract-v1.zh-CN.md
factorforge-epistemic-host-readback-meta-registry-v1.json
factorforge-epistemic-host-readback-closed-schema-bundle-v1.json
factorforge-epistemic-host-readback-stage1b0-review-checklist-v1.zh-CN.md
```

packet manifest作为非自哈希binding envelope，不进入其自身`artifacts[]`；其余四个文件构成exact artifact set。

上游 exact baselines：

```text
P0 manifest = 58c3585881f52c4ed60c4e7fb582e9b30acf0063433c12363915d54f0b985c4f
Stage1A commit = 07850b6886380aa961e1507d8f3a8df91fe204a6
current operating-code baseline = dc6f55ab6ea1f9dc32518e3af02df4a9e5d423ee
closed-schema bundle raw file SHA-256 = 43d33b4499a82e69183cc5f0f8f3df116fb97545c892f44f098b9b81cac8e316
```

reviewer 不得读取 live Host、private locator、canonical payload、secret 或 OOS，不得修改任何文件。
本 review 不请求 collector、signer、verifier、key、control store、P1A、Skill、RAG、shadow 或 runtime
implementation authority。

合法 verdict 只有：

```text
STAGE1B0_META_DESIGN_GO__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING
STAGE1B0_META_DESIGN_REVISE
```

## 2. Mechanical checks

1. 重算 delivery packet manifest 和全部 artifact SHA-256；
2. 确认logical packet闭包恰为manifest加4个listed artifacts，4个artifact均regular/single-link且无symlink；
   当前source directory不是dedicated packet root，目录内unlisted文件不进入review scope；若另行导出dedicated
   delivery root，该root才必须恰含这5个文件；
3. JSON registry 与 closed-schema bundle 可严格解析、无 duplicate key/nonfinite/lone surrogate；bundle通过
   Draft 2020-12 meta-schema，本地 `$ref` 全部闭合；
4. P0 manifest、Stage1A commit 和 current baseline exact match；
5. exact universe 为5 authorities、3 roots、2 endpoints、4 relationships、12 stores、24 SoD、
   33 principals、67 events、1 external trust、101 deployment rows、40 adapters、167 material subjects；
6. `EPB-HYP-EVO` 与5个future adapters仍为 absorbing `NOT_AUTHORIZED`；
7. meta-registry authority ceiling 九项全部为 exact boolean `false`。
8. schema bundle 的16类legacy public artifacts（8 dependency/control + 2 external prerequisite + 6 runtime
   chain）、5 observation branches、7 subject families、4 physical backends均为closed
   oneOf/required/type/cardinality/`additionalProperties=false`；16不是route/compiler-root计数，semantic
   extension不可被忽略；
9. 167 material partition exact等于161 eligible + 6 prohibited；24 SoD是单独gating vector而非material leaves。
10. 独立重建 closed-schema definition universe：`$defs` exact 381；roots 0..39 的 transitive local-ref closure
    exact 258；root-40 nonroute subroots exact 123；两集合不重叠且 `258 + 123 = 381`，definition ID、
    fragment hash、ordinal 与 manifests 全部重算一致。
11. 重建 Projector-SoD 固定计划及 resolver transcript：authority comparison rows exact 193、validator
    nonself rows exact 3；full session-private transcript 的六个 leaf partition exact为
    `6+5+4+2+167+3=187`，pairwise crosswalk exact为`193*2+3*2=392`；ordinal、selector、target、
    raw/schema/native-validation result及全部manifests必须双射、全PASS、零unresolved/ambiguous/failure。
    public ref必须精确等于schema冻结的25-field closed metadata projection，并固定session-private retrieval/
    storage scope；不得包含leaves、native results、crosswalk、overall PASS verdict或failure counts，且不能
    单独证明PASS。private resolution PASS不是adjudicative PASS，semantic receipt才是唯一裁决truth。
12. 机械检查 owner/selector/policy closure：五个 signing-role owner source只能走trust-binding E projection，
    六个projector/validator/auxiliary owner source只能走OS/HW-rooted E projection，T0不得进入；owner
    evidence ref只有一个active nested projection digest；typed owner不得有自由`source_id`、第二outer digest
    或caller-selected basis；selector V3的external 0..4必须绑定exact typed predecessor identity，SELF 5
    必须使用precontent profile、empty raw digest且禁止predecessor；trust与OS/HW policy branch不得交叉；
    owner-equality scope delta必须保持
    `DESIGN_ONLY__INDEPENDENT_OPERATING_AUTHORITY_APPROVAL_REQUIRED__UNBOUND_BLOCKING`，approval receipt为空，
    measurement root只能签已解析E-equality且不得生成/选择owner或授权execution。
13. 独立重建 mandatory-conformance registry：Rule6/11/16/27/31 counts exact为`10/36/50/43/31`，
    bases exact为`0/10/46/96/139`，global ranges exact为
    `0..9/10..45/46..95/96..138/139..169`；total exact 170、global ordinal exact `0..169`、token唯一且
    source/local/global三向双射；minimum case count exact 261；preflight与两个fixed-order labels必须分别
    使用`EXACT_170`、`ALL_170`，不得保留旧计数。
14. 核验 authority ceiling 未扩张：authority count仍为5，`r3_normative_role_universe_modified=false`，bundled
    routes仍为33，execution-role enum仍为14，identity-commitment purpose counts仍为global 3、subject 167、
    protected namespace 8；不得因owner projection、resolver transcript、selector V3、provenance compiler或
    Projector-SoD proof新增principal、key、purpose、route、admission或canonical authority；
    `deployment_rows_created=false`必须保持不变。

## 3. M-D1–M-D18

| Decision | Reviewer 应确认的内容 |
|---|---|
| M-D1 control authority | control plane 只有 deployment-evidence authority，不创建第二 canonical authority，也没有 runtime/semantic/OOS authority |
| M-D2 bootstrap | protected out-of-band bootstrap pin set exact绑定Host/verifier/external-authorization/external-isolation四个distinct trust pins与两个external issuer identities；request/response/packet不能self-pin |
| M-D3 role universe | session issuer、collector、Host attestation issuer、verification-target author、independent verifier 五角色闭合 |
| M-D4 SoD | 五角色 principal/context/capability closure、五把purpose keys两两不同；两把content keys不能签control action；independence receipt由五角色之外预先签发；同UID/label不算独立 |
| M-D5 R3 isolation | `FF_SNAPSHOT_ISSUER_V1` 与全部167个subjects都是被绑定对象，不能参与Stage1B bootstrap |
| M-D6 control state | readback control ledger与verification registry预先存在、out-of-band绑定且物理上位于全部subject roots之外 |
| M-D7 schema/DAG | schema bundle机器闭合；四份phase grants共享exact authorization context；两份control receipts均reserve→sign→external-finalize；challenge→target→Host receipt/finalize→verification target→verifier receipt/finalize→effective snapshot strictly acyclic |
| M-D8 canonical/signature | RFC8785 JCS、content/action domains分离、completed action-signed digest、exact signature input、receipt自哈希禁止、outer file hash位置唯一 |
| M-D9 atomicity/replay | 167 rows按Stage1A exact family/within-family order且同一cohort/commit/four trust generations/policy/window；exact nonrevocation snapshot refs与closed consistency paths；两个expected control heads、one-shot CAS、stale/fork/fallback拒绝 |
| M-D10 physical/identity proof | 四关系、八类forbidden relationship、4-backend oneOf、closed applicability/collision manifests、session-purpose HMAC commitment完整；raw locator不出Host boundary |
| M-D11 status law | 五个observation evidence branches不需dummy positive evidence；两个pre-verifier targets均不能含`BOUND_VERIFIED`；最终状态只在PASS receipt finalize后由externally pinned projector产生；24 SoD gating；NOT_AUTH absorbing；167-row fold唯一 |
| M-D12 sanitization/gates | closed allowlist、零异常回显；GO仍只允许后续独立授权，不授权collector/signature/runtime |
| M-D13 private resolver | exact 187 typed leaves与392-row crosswalk只能存在于session-private transcript；每个leaf均须解析raw bytes、通过pinned schema与native validation；public ref是exact 25-field closed metadata projection，只作opaque content-addressed引用，不能独立声明PASS |
| M-D14 owner-source equality | 五个trust-binding E与六个OS/HW-rooted E分支闭合；active projection basis是唯一digest owner；typed owner只能等于所选resolved projection，不得有自由source ID、outer hash、alternate/self-attested source或branch cross；measurement root只签已解析E-equality，独立operating-authority approval缺失时保持UNBOUND且不得生成/选择owner或授权execution |
| M-D15 selector/policy | selector V3的external 0..4 exact绑定各自typed predecessor，SELF 5只绑定projector precontent且无predecessor；11-row accepted-L0 owner policy与T1 row/phase occurrence逐项相等，trust与OS/HW branch cross一律BLOCKED |
| M-D16 protected SoD proof | 193 authority comparisons与3 validator-nonself rows来自固定static plan，caller不得增删、排序或选择；runtime rows必须逐字节等于static rows；projector、structural validator、semantic validator及WASM validator均不得自证或互相替代 |
| M-D17 provenance/root29 | 381-definition meta-root由258 route-reachable与123 nonroute subroots精确闭合；root29逐字段完整展开path AST和oneOf discriminator，D/R/E/T/S均有有效partition、H exact 0；D preimage不得含raw private identity，R不得退化为bare hash；binding commitment→family row与两类family manifests→occurrence row/manifest→partition basis→registry digests/ref必须逐项重算、完整传播且无回边 |
| M-D18 receipt/DAG/conformance | protected bundle→private transcript→public ref→semantic receipt→input-equality projection→V3 proof→snapshot严格单向；semantic receipt是唯一adjudicative PASS truth，private transcript PASS仅为resolution verdict，equality只重验/投影相等关系且不得创建second truth；170 mandatory obligations及minimum 261 cases全部执行才可进入后续状态裁决 |

## 4. 必须重点攻击的 bootstrap loops

reviewer 应逐项尝试证明以下 loop 是否仍可能发生：

1. response 自报 trust manifest/key/role，随后用该 key 验证自己；
2. `host_admission` generic key 被无 delta 复用为 Host issuer 或 verifier；
3. `FF_SNAPSHOT_ISSUER_V1` 签自己的 deployment row；
4. deployment control ledger 位于 canonical-memory/transaction/delivery root 内；
5. verification target author 与 verifier signer 是同 principal/context；
6. Host attestation 与 verifier 共享同一个未独立批准的 trust pin；
7. target 包含 future receipt hash，或 receipt 将自己的 signature/hash 纳入 preimage；
8. outer packet manifest 与内部 content/receipt hash 形成循环；
9. 新 unverified generation 发布后 consumer fallback 到旧 verified generation；
10. 部分 row PASS、critical-subset 或 coverage threshold 被解释为 whole `BOUND_VERIFIED`。
11. 五个 control-plane roles 中任一角色自签、互签或临时创建 independence receipt。
12. issuer/verifier可在没有对应content-author signature时代写target，或下游只绑定不含signature的`receipt_id`。
13. 所有签名错误复用一个pre-session nonrevocation head，或缺少anchor→signing-head consistency proof。
14. ABSENT/PARTIAL/BLOCKED row被迫填positive family evidence，或unknown通过dummy proof变成ABSENT。
15. 24 SoD被重复计入167 leaves、2 endpoints未参与fold，或161+6 partition不闭合。
16. identity hash由caller自选salt/hash，或collision/applicability集合用开放文字动态缩域。
17. signed receipt包含后置CAS finalization result，或ledger finalization要求receipt预先包含自身completed digest。
18. verification target在future verifier PASS/signature之前写`BOUND_VERIFIED`或最终row/overall status。
19. bootstrap pin set可从request/packet注入，或session issuer可自行选择trust pins、proof/applicability、policy、
    code/config、expected heads或challenge scope。
20. 四份phase authorization receipts没有共享byte-identical `authorization_context`，没有独立
    `STAGE1B_SESSION_CHALLENGE_ISSUANCE` branch，或仍以opaque scope hash代替closed grant。
21. trust/nonrevocation、subject requirements、proof applicability、protected namespace、reservation/finalization
    任一dependency只有prose/hash而无closed schema及逐字段binding。
22. effective-snapshot projector code/config没有进入external authorization allowlist，或snapshot可接受self-reported/
    fallback projector identity。
23. 只持有public transcript ref、bundle hash或单边evidence即可伪造resolver PASS，而无需重新解析187 leaves
    和392 crosswalk。
24. caller可省略、重排或重复private leaf/crosswalk row，或以bare hash替代raw bytes、schema validation和
    typed native PASS。
25. owner evidence ref出现第二projection digest、alternate owner、自由`source_id`或caller-authored basis；
    typed owner未严格等于selected source basis。
26. external selector改指非本ordinal predecessor，或SELF selector携带predecessor、非empty raw digest、
    postcontent/successor digest。
27. signing role走OS/HW branch，projector/validator/auxiliary role走trust-binding branch，或T0 hash被注入
    accepted-L0 T1/phase policy。
28. 193+3 runtime rows由caller选择、与static plan不等，或projector与structural/semantic/WASM validator
    发生self-attestation、alias或相互替代。
29. root29用category selector、literal star、first-array-item shortcut、缺失oneOf discriminator或generic
    enforcement profile；R仅验证hash，D preimage包含private identity；binding commitment、family row、
    family/binding manifests、occurrence row/manifest、partition basis、registry digest/ref任一未重算、未传播
    或含successor backedge。
30. semantic receipt未同时绑定bundle与public transcript ref，equality projection未重新验证private transcript，
    equality被视为第二个PASS truth，或V3 proof/snapshot向前序digest回写形成second truth/cycle。
31. 170-vector集合被缩域、ordinal/base/range漂移、preflight/fixed-order仍引用旧计数，或新增schema借机扩展
    authority、principal、role、key、purpose或route。
32. owner-equality scope delta没有独立operating-authority approval却被视为已批准，measurement root可生成、
    规范化、选择或修改owner identity，选择role/phase/grant/policy、授权execution、创建deployment row或扩展
    R3 role universe。

任一 loop 可行即 `REVISE`。

## 5. Status oracle

| Condition | Exact result |
|---|---|
| prohibited subject actualized/uplifted | `NOT_AUTHORIZED__UNBOUND_BLOCKING`，no consumable snapshot |
| any material subject missing/unknown/unreadable/stale/unbound | `UNBOUND_BLOCKING` |
| no unbound subject and remaining gaps are only exact partial-native seams | `PARTIAL_NATIVE_SEAM__UNBOUND_BLOCKING` |
| all eligible subjects exact-closed, prohibited negative proofs valid, complete two-trust chain and independent PASS | `BOUND_VERIFIED` |

第四行也只证明 exact deployment binding。所有 runtime/RAG/Skill/canonical/OOS/next-gate authority 仍为
false。

上述新增 closure 全部 GO 仍只构成 design closure；private transcript、deployment identities、runtime rows、
receipts与proof尚未materialize和执行时，最终 verdict仍只能是
`STAGE1B0_META_DESIGN_GO__DEPLOYMENT_REMAINS_UNBOUND_BLOCKING`，不得解释为deployment、runtime、Skill、
RAG、canonical或OOS授权；owner-equality scope delta的独立operating-authority approval为空时也保持同一
阻断状态。

## 6. Explicit non-authorization matrix

| Action | Stage1B-0 GO 后是否允许 |
|---|---|
| create/init/migrate Host store | NO |
| generate or repurpose keys | NO |
| implement/read live Host collector | NO；需单独 Stage1B-1 authorization |
| sign challenge/target/receipt | NO |
| implement independent verifier | NO；需单独 Stage1B-3 authorization |
| output `BOUND_VERIFIED` | NO |
| materialize/execute P1A fixtures | NO |
| approve or execute owner-equality scope delta | NO；需独立 operating-authority approval |
| modify Ultimate/Step Skills | NO |
| run RAG/shadow/runtime | NO |
| read canonical payload/OOS/secret | NO |

## 7. Reviewer response format

请返回：

1. exact manifest identity 与 mechanical closure；
2. M-D1–M-D18 逐项 `GO|REVISE`；
3. P0/P1 blockers 与最小修复；
4. role/SoD/trust bootstrap 裁决；
5. hash/signature cycle 与 status aggregation 裁决；
6. 最终 verdict，限定为本 checklist 的两个 token之一；
7. 明确说明未读取 live Host/OOS/canonical payload/secrets、未修改文件。
