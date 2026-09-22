# Factor Forge Epistemic Kernel 离线候选使用说明

这是可执行的本地候选，不是架构说明书。它把四段真实代码串成一个入口：

1. 先理解研报或用户假设，并冻结 blind mechanism seed；
2. 在 blind seed 之后检索因子知识图谱；
3. 分别返回 exploit、explore、near-miss 和 counterexample 建议；
4. 可选地把 Step4/5 失败证据编译成可执行的区分性测试计划。

它不会读取 OOS、不会写 canonical memory、不会修改正式 Skill，也不会执行诊断试验或作出因子晋级结论。

## 直接运行

示例输入已经绑定当前本地知识图谱：

```bash
FF_KERNEL_ROOT=/Users/humphrey/projects/factor-factory-epistemic-s4-native-kernel-20260831
FF_KERNEL_OUTPUT_PARENT=/Users/humphrey/projects

python3 "$FF_KERNEL_ROOT/scripts/build_factorforge_epistemic_kernel_offline_candidate.py" \
  --input "$FF_KERNEL_ROOT/examples/factorforge_epistemic_kernel_wavelet_demo_input.json" \
  --allowed-output-parent "$FF_KERNEL_OUTPUT_PARENT" \
  --output-root "$FF_KERNEL_OUTPUT_PARENT/factor-forge-epistemic-kernel-local-run-001"
```

发布位置是 fail-closed 的固定边界：

- `--allowed-output-parent` 必须与当前 `REPO_ROOT.parent` 是同一路径、同一 device/inode，不能通过 symlink 或另一个任意目录替代；
- `--output-root` 必须是该 parent 的直接子目录，目录名必须以 `factor-forge-epistemic-kernel-local-run-` 开头；
- output root 必须不存在；repo、`knowledge`、`factor_research`、OOS、canonical、runtime、deploy 等受保护根、其后代与物理别名均会被拒绝；
- 发布器只创建这个新的 sibling 目录，采用 create-only 语义，不覆盖旧结果。

创建和写入使用固定 parent directory fd、`mkdirat/openat` 等价语义以及
`O_DIRECTORY|O_NOFOLLOW`。所有文件都通过同一个 output directory fd 以相对叶名称
create-only 写入；每次写入前后都会比较 parent 与 output entry 的 device/inode。
即使另一个进程在创建后置换路径，发布器也会阻断，且不会沿替换后的路径写入受保护根。

发布前不会先创建目录。发布器会使用原始 input payload 重新执行
`build_candidate`，要求重建结果与调用方传入 candidate 完全相等，再显式运行
composition validator。任一 replay、content hash、schema 或 validator 不一致都会在
首次写入前终止。

输出恰有三个文件：

- `00_epistemic_kernel_candidate.json`：发布时已用原始输入完整重放验证、但交付后不自包含的机器对象；
- `01_chief_research_advisory.json`：给研究 Agent 直接消费的精简建议；
- `packet_manifest.json`：文件 bytes 和 SHA-256 清单。

输入中的 `session_scope_secret_hex` 只用于生成 session-scoped opaque handles。发布前会用
原始 secret bytes、大小写 hex 和规范 Base64 表示扫描 candidate、advisory 与 manifest；任一
表示命中都会阻断，输出目录也不会创建。

Manifest 的 `candidate_only`、`signed`、`authority_effect`、canonical/OOS 状态及候选状态
均取自重放后且已通过 composition validator 的对象；`replay_validation` 保存 exact-equality、
canonical-bytes equality、validator 与 secret-scan 的派生结果，不接受调用方声明。

该证明明确只是 publisher-time replay validation，并非 self-contained 或 standalone replay。
Manifest 的 `publisher_time_replay_scope` 固定声明这一边界，并列出重新执行所需的外部依赖
类别：原始输入、source/lineage、retrieval knowledge、可选诊断 bytes、composition/validator
代码及 schema/contract 实现依赖。session secret 不持久化，因此仅凭交付包不能独立重放。

## Step1 来源边界

`formalization_provenance.field_rows` 对 14 个语义字段逐项标记：

- `CALLER_CLAIMED_SOURCE_GROUNDED`：调用方声称由选中的源文陈述支撑；本地词法检查只作为候选一致性门，不构成独立 source-reader 证明；
- `PRE_RETRIEVAL_ANALYST_INFERENCE`：检索前分析推断；
- `NEW_ASSUMPTION`：新假设，不冒充原文；
- `UNRESOLVED`：仍待澄清。

适配器会检查 statement ID、分类和本地语义锚点，但没有独立 source-reader attestation，因此不会声称“调用方一定没看过知识库”。输出明确保留：

```text
caller_semantic_origin_independently_verified = false
strong_no_knowledge_consultation_attestation_present = false
```

知识建议只能补充 blind seed，不能回写或改写本轮源文理解。

## Exploit / Explore

Retrieval stage 仍保留逐 lane 的底层选择记录；Chief advisory 会先按
`precedent_group_handle` 去重，同一个历史先例只在 `precedent_groups` 中出现一次，
并把它在不同 lane 中的用途写入 `lane_assignments` 与 `lane_role_rationale`。因此一个同时
构成 near-miss 和 counterexample 的先例不会被冒充为两个独立经验。
`information_preserved` 与 `information_lost` 只保留源节点中可明确分开的原文子句；若两者
为空，表示该源节点没有记录这种信息代价，候选不会为填满字段而自行编造解释。

去重后的角色引用直接分为：

- `exploit_candidates`：结构同构、可复用的既有机制；
- `explore_candidates`：跨数学族类比；
- `challenge_candidates`：按先例分组的 near-miss failure 与 direct counterexample 角色；同一先例可以同时承担两种挑战角色。

三组都允许为空，不生成 dummy branch，也不根据历史收益替 Agent 选模型。下一步是 Agent 在 A0 之后完成 competing-model diversification 和 mechanism-conditioned measurement program，而不是直接跳到 Step2/Step3。

## Step4/5 失败诊断输入

Python 组合 API 接受原始 bytes：

```python
diagnosis_inputs = {
    "stage2_manifest_path": stage2_manifest_path,
    "fixture_raw_bytes": fixture_path.read_bytes(),
    "assertion_dependency_raw_bytes": assertion_dag_path.read_bytes(),
}
```

CLI JSON 则使用两个显式绝对路径：

```json
{
  "stage2_manifest_path": "/absolute/path/to/stage2-packet/packet_manifest.json",
  "fixture_json_path": "/absolute/path/to/diagnosis-fixture.json",
  "assertion_dependency_json_path": "/absolute/path/to/assertion-dependency-dag.json"
}
```

适配器只接受真实 Stage2 manifest path，或直接接受该 manifest 的原始 bytes；二者必须恰选其一。它会内部重放 closed Stage2 compiler，并对 Stage2 manifest、fixture 和 assertion DAG 自行重算 SHA，调用方不能再注入一个“自洽重哈希”的任意 binding。每份诊断候选都有独立 `diagnosis_id`，绑定 Source-First session、Stage2、两份原始诊断输入与 target/hypothesis；组合层 `session_id` 又绑定所有 stage output，因此更换诊断目标不会复用同一分支身份。输出仍只是一份诊断计划：它保留 rival、partition、distinguishing test、lower-layer clearance 与 future-question 约束，但不会执行测试、识别原因或签发 qualification。

## 当前接入状态

本候选现在已接入 repo 内 `run_factorforge_ultimate.py` 的默认关闭 shadow seam。显式
request 可以在 Step2 前生成 Source-First/A0 advisory，或在满足隔离条件的 Step5-only
运行后生成失败诊断计划；详细命令见
`docs/operations/factorforge-ultimate-epistemic-shadow.zh-CN.md`。

这仍不是已安装 Skill 或正式 operating contract 的激活：shadow 不进入 formal commands、
proof、verdict、Council、OOS 或 canonical memory，失败也不能改变正式返回码。S6 仍需
独立 operating-contract delta、Skill 激活与 production 验收。
