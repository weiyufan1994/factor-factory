# Ultimate epistemic advisory / shadow 使用说明

S6 已把 S4/S5 research-brain kernel 激活为 Ultimate Agent 内部的 candidate-only
advisory route。对用户仍只有 `factor-forge-ultimate` 一个入口：Agent 先独立理解来源，
再自动配置 RAG 并读取 advisory；用户不需要管理知识索引、lane、session secret 或 shadow
命令。原有 wrapper observation sidecar 仍然显式、默认关闭。两条路径都不能改变正式
Step1–6 命令、proof、factor verdict、Council、OOS 或 canonical memory。

## S6 自动 Source-First bridge

新研报或用户假设必须先由当前研究 Agent 在不读取因子知识、历史案例、当前因子结果、
代码或数据可得性的上下文中完成 source-only reading，并把 source-native claim、agent
paraphrase/inference、new assumption 和 unresolved 项分别写入：

```text
<factor-workspace>/candidate_epistemic_shadow_inputs/source-first-overlay.json
```

Overlay 使用 `factorforge_epistemic_agent_source_first_overlay_v1`。这些经济语义不能由
deterministic code、`alpha_idea_master` 或回测指标猜测。完成 freeze 后，Ultimate Agent
内部运行：

```bash
python3 scripts/run_factorforge_epistemic_source_first_advisory.py \
  --factor-workspace <factor-workspace> \
  --report-id <report-id> \
  --source-first-overlay \
    <factor-workspace>/candidate_epistemic_shadow_inputs/source-first-overlay.json
```

CLI 不接受 RAG path、lane 或 secret。它先用纯内存 Source-First compiler 验证并冻结 blind
seed，成功后才解析 repo canonical knowledge indexes、生成一次性 session secret 并执行
retrieval。Secret 不进入 exact3 package。随后 Agent 必须运行专用 package validator；只可
消费 validator 从已验证内存对象直接输出的 advisory JSON，不得再按路径打开
`01_chief_advisory.json`，然后才可完成正式 conjecture。检索结果
只能作为 prior/counterexample/tool candidate，不能改写 frozen source understanding 或直接成为
Step1–6 输入。

```bash
python3 scripts/validate_factorforge_epistemic_source_first_advisory.py \
  --receipt <bridge-emitted-02_shadow_receipt.json>
```

该命令只在完整重放通过后把已验证的 advisory JSON bytes 写到 stdout；非零退出即 BLOCK。
Agent 必须直接消费这份 stdout，不得再打开 advisory 路径而制造验证后置换窗口。

validator 的 expected Factor Forge root 来自当前 Ultimate operating context 的外部绑定，不能
由 workspace manifest 自证或由 caller 替换。每个 source-first 尝试使用稳定 attempt state；
重试只能恢复或验证同一尝试，不能再生成第二个 candidate package。缺少、冲突或漂移的 state
必须阻断 advisory consumption。Attempt identity 同时绑定 Source-First 编译结果和 canonical
knowledge-file snapshot；知识快照真实变化时会生成新的 content-addressed attempt，不会覆盖旧包。

若原始 source、合法可得时间、locator、selection/outcome exposure、provenance 或 pre-A0
prediction 无法诚实建立，则 bridge 在知识索引被解析前阻断。Agent 应澄清或 lawful
abstain，不能用 `alpha_idea_master` 反推来源。

## Legacy/manual S5 Step1 observation sidecar（不是 S6 默认路径）

本节只保留给 wrapper 兼容调试、冻结 S5 重放或已经存在 closed kernel request 的维护任务。
它不是 S6 新研报/用户假设的正常入口，Ultimate Agent 不得要求用户准备 `kernel-input.json`、
request path 或 `--epistemic-step1-shadow-request`。S6 默认路径是上面的 pre-Step1 bridge：
只需要 Agent 自己撰写 source-only overlay，不要求 `alpha_idea_master`，也不需要 wrapper flag。

当前 Ultimate 的正式命令域从 Step2 开始。因此该 hook 要求 workspace 已有冻结的
`alpha_idea_master`，推荐且唯一有意义的接法是 `start-step=2`；它不会在同一次调用里
代替 Step1 生成正式 artifact。

先在隔离 factor workspace 中准备 S4 closed input：

```text
<factor-workspace>/candidate_epistemic_shadow_inputs/kernel-input.json
```

`factor-workspace` 必须通过仓库原生 `manifest.json` 合同，并精确落在该 manifest 绑定的
`<factorforge-root>/factor_research/<factor-id>/<research-id>`；任意目录、自写 runtime manifest、
受保护根、symlink、mount 或跨设备别名均不能取得候选写权限。

然后生成 closed request：

```bash
python3 scripts/build_factorforge_epistemic_shadow_request.py \
  --factor-workspace <factor-workspace> \
  --report-id <report-id> \
  --kernel-input <factor-workspace>/candidate_epistemic_shadow_inputs/kernel-input.json
```

在上述 legacy/manual 调试范围内，wrapper 调用为：

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id <report-id> \
  --start-step 2 \
  --end-step 2 \
  --factor-workspace <factor-workspace> \
  --epistemic-step1-shadow-request <request-path>
```

Shadow 只允许 `start-step=2`，并要求已有 canonical path、合法 contract/producer/source
identity 的冻结 `alpha_idea_master`。它在正式 preflight 与 proof 初始化完成后、第一条
Step2 命令执行前运行。即使 shadow 被阻断，正式 Ultimate 返回码、命令闭包和 proof
也保持独立；console 只显示固定的 `EPISTEMIC_SHADOW` 状态。

## Step5 failure-diagnosis shadow

Failure request 的 kernel input 必须包含合法 `diagnosis_inputs`，并显式声明当前目标
factor ID：

三项 JSON 输入必须是以下专用根的三个不同普通文件；外部路径、symlink、hardlink、mount、
跨设备文件、子目录和同 inode 复用均 fail closed。所有 live binding 还会在 build 前后、
receipt 写入前后及 consumer replay 时重验 `device/inode/link_count/mtime/bytes/SHA`：

```text
<factor-workspace>/candidate_epistemic_shadow_diagnosis_inputs/
```

这只证明 shadow 没有直接打开 protected OOS/canonical/Host 根；它不替 caller 为复制进
candidate root 的字节签发来源证明。因此 receipt 明确记录
`candidate_input_provenance_independently_verified=false`，不能据此把未知来源字节解释成
合法 OOS 或 canonical evidence。

```bash
python3 scripts/build_factorforge_epistemic_shadow_request.py \
  --factor-workspace <factor-workspace> \
  --report-id <report-id> \
  --kernel-input <factor-workspace>/candidate_epistemic_shadow_inputs/failure-input.json \
  --hook POST_STEP5_FAILURE_DIAGNOSIS_SHADOW \
  --diagnosis-target-factor-id <factor-id>
```

调用 Ultimate 时增加：

```text
--epistemic-failure-shadow-request <request-path>
```

这条 hook 只在本次 Ultimate 内存中的最终 proof 已写定、`end-step=5`、完整正式 command
contract 通过、`formal_proof_eligible=true`、current authority 已验证，且 EVO、Web/OOS、
recovery、revision 均明确未使用时运行。Wrapper 会在正式 `validate_step5` 命令前后捕获
exact6 artifact 的 bytes/SHA/物理身份并要求完全相等，在 proof seal 前再重放一次；子进程
随后同时重放 exact6 snapshot 与 proof，防止把验证后的另一代 artifact 回填进当前诊断。
它只编译诊断问题、rivals 和 distinguishing-test plan；不执行测试，不把原因标成
`IDENTIFIED`，也不签发 qualification。

## 输出

每次运行先在私有 staging 目录写完并完成 receipt 前后输入重放，再把完整包一次性显现为
workspace 独立候选根下的 exact3 文件：

```text
candidate_epistemic_shadow/shadow_<content-id>/
  00_kernel_candidate.json
  01_chief_advisory.json
  02_shadow_receipt.json
```

Receipt 绑定 native workspace manifest、当前 runtime manifest、request、冻结正式 artifacts、failure exact3 输入及
本次最终 Step5 proof 的 bytes/SHA/物理身份，
并固定：

- `candidate_only=true`
- `signed=false`
- `authority_effect=NONE`
- `formal_command_contract_changed=false`
- `formal_proof_eligibility_contributor=false`
- `factor_verdict_contributor=false`
- Step2–6 均为 forbidden consumer

其中 `canonical_memory_or_oos_accessed=false` 专指没有访问 canonical memory 或 OOS；它不否认
Source-First bridge 已显式读取 public repository knowledge indexes。无论如何，该 route 都没有
canonical-memory write、Host、OOS、production、qualification、promotion 或 official writeback
authority。

Request 缺少 S4 exact input 时必须阻断。系统不会从 `alpha_idea_master` 猜出 statement
locator、exact14 provenance 或 pre-A0 prediction，也不会把 agent inference 冒充成
source-grounded evidence。当前 request builder 会把 exact8 顶层来源诚实标记为
`CALLER_SUPPLIED_PRE_RETRIEVAL_CANDIDATE`；自动的逐字段 Step1 derivation mapper 属于后续
易用性增强，不是本 shadow receipt 已经拥有的 source authority。

## 当前边界

S6 只激活 Research Agent 对 candidate advisory 的使用；formal wrapper 内的 shadow flag
仍默认关闭，正式命令合同未改变。子进程环境不继承 `FACTORFORGE_*`、AWS/S3、Host/OOS
token。路径展开、子进程、receipt 校验或打印链路上的任何普通 exception 都不能覆盖正式
Ultimate rc。

Advisory Exploit 与 Explore 各自允许 `0..N` 和合法 abstention/Neither，但正式 Step6
multibranch validator 仍按现行合同运行，candidate 不得直接喂给 child/handoff。Post-Step5
新解释只能进入 rivals、distinguishing-test plan 或 future-question namespace；若缺少真实
diagnosis seed，记录 `ADVISORY_NOT_RUN__DIAGNOSIS_SEED_UNAVAILABLE`，不得从 metrics 自动
制造 fixture、root cause 或 qualification。
