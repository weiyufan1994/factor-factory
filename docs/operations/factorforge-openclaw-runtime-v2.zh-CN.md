# Factor Forge OpenClaw Runtime V2 SOP

## 目标

OpenClaw/Humphrey 只作为 Factor Forge 的消息入口和工具宿主，不再作为生产事实判断器。所有运行、状态、SSM、artifact root、proof 判断必须通过：

```bash
python3 scripts/factorforgectl.py ...
```

## Humphrey 允许做什么

Humphrey 只能：

1. 根据用户意图选择 `factorforgectl.py` 子命令。
2. 传入 `report_id`、PDF S3 URI、worker instance id 等显式参数。
3. 将 `factorforgectl.py` stdout JSON 摘要转述给用户。
4. 遇到任何 `BLOCK`、工具失败、路径读取失败、preflight 失败时，先执行
   `recover-block`，再按其 `allowed_next_commands` 继续。

## Humphrey 禁止做什么

Humphrey 禁止：

- 自行 `find` / `grep` artifact root 来判断状态。
- 自行扫描 `/tmp`、workspace 顶层 `objects`、旧 archive root。
- 自行列 S3 tgz 并把旧 snapshot 当作当前 run 证据。
- 自行查询 SSM history 后拼接运行结论。
- 将 worker `stopped` 解释为 run 失败。
- 用同 report_id 的旧 artifact 替代 active registry 指向的 root。
- 手工 patch raw LLM artifact。
- 直接调用 `prepare_factorforge_formal_artifacts.py` 或其他底层脚本写 formal artifacts；
  正式写入只能通过 `factorforgectl.py`。
- 使用 `sessions_spawn` / sub-agent 代写 Step1/Step2 raw JSON。Step1 raw 只能来自
  OpenClaw `tools.pdf`，Step2 raw 只能来自 formal LLM bridge，且必须通过 provenance
  与 schema 校验。
- 在 `recover-block` 之前自行 `show` manifest、proof、runtime_context 或旧 root。
- 修改 registry、manifest、runtime_context 或 raw JSON 来绕过 BLOCK。
- 在正式 `挖因子` 流程使用 `--allow-deterministic-debug` 或 `fixture`。

## BLOCK 恢复规则

`BLOCK` 是控制流，不是聊天解释题。Humphrey 遇到任何失败后，必须立即停止
当前步骤，并只运行：

```bash
python3 scripts/factorforgectl.py recover-block --report-id <report_id>
```

`recover-block` 是只读诊断命令。它只读取 active registry 指向的当前
`artifact_root` 下的 manifest、proof ledger、prepare report、runtime_context，
并输出：

- 当前 active `run_id`
- 当前 active `artifact_root`
- registry / manifest / runtime_context 身份是否一致
- 当前 `diagnosis`
- 唯一允许的 `allowed_next_commands`
- 禁止动作列表

Humphrey 必须按 `allowed_next_commands` 执行。若 `recover-block` 返回身份不一致、
旧 SHA、缺少 manifest、缺少 runtime_context 等 BLOCK 诊断，Humphrey 只能回报
诊断并等待用户授权 fresh run；不得 show 旧路径、不得扫描目录、不得跳过 preflight。

权威状态优先级固定为：

```text
active registry > active artifact_root manifest > active proof ledger > active prepare report/runtime_context > 当前命令 stdout > 聊天历史 > deprecated old artifacts
```

聊天历史和旧 artifacts 永远不能覆盖 active registry。

## 标准命令

## 固定口令

`factor-mining` / `挖因子` 是本流程的用户口令别名。

当用户说：

```text
FactorForge V2 dry-run: 使用附件 PDF
```

或等价表达如“按 Factor Forge V2 真实研报 dry-run 流程处理这篇附件研报”，
Humphrey 必须按以下固定语义执行，不需要用户重复长规则：

1. 只允许使用本次附件 PDF / 本次明确指定的新研报作为 source report。
2. 必须先回报并绑定 PDF `local_path`、`sha256`、可用时的 `source_uri`。
3. 必须生成全新的 `report_id`、`run_id`、`artifact_root`。
4. 禁止使用 `fixtures/step1/kakushadze_101_formulas.pdf` 或任何 repo fixture，除非用户明确说这是 smoke test。
5. 禁止使用旧 `/tmp` root、旧 artifact root、旧 report_id 或旧 SSM/S3 证据替代 active registry。
6. Step1 必须走 OpenClaw `tools.pdf` agent-tool 路线，写入 primary/challenger/chief 三份 raw。
7. Step1 raw/schema 禁止手工 patch；必须由 `resume-step1` 校验 provenance 后继续。
   `resume-step1` 记录的 Step1 raw SHA 是 Step2 的硬前置条件。任何后续改动
   Step1 raw JSON，`run-local --start-step 2` 必须返回
   `BLOCK_AGENT_TOOL_STEP1_RAW_TAMPERED`。
8. Step2/3A 默认必须使用真实 provider 路线 `--formal-llm-provider command`；禁止使用 `fixture`，除非用户明确说这是 smoke test。
   Step2 的 `direct_code` 不只检查 schema 和性能，也必须检查公式语义。若公式要求
   `past N=20 valid trading days` / rolling lookback，则禁止用全历史
   `rank().over('ts_code')`、`count().over('ts_code')`、重叠 top/bottom
   阈值或 `(ts_code, trade_date)` 单点聚合冒充窗口内 `V_high/V_low`。
9. 主机侧必须分步执行并逐步汇报：Step1 完成后停；用户确认后 Step2；Step2 完成后停；用户确认后 Step3A；Step3A 完成后停。
10. 只允许执行到 worker dry-run：`check-worker`、`sync-worker-artifacts --dry-run`、`run-worker --dry-run`。
11. 禁止真实 `sync-worker-artifacts --poll`、真实 `run-worker --poll`、Step3B/4/5、Step6、search/promotion，除非用户另行授权。
12. 用户授权进入真实 worker 后，研究机内 Step3B/4/5 可以作为一个连续作业 `3b->5` 执行；完成后必须汇报 proof 并等待用户验收，不得自动 Step6 或 stop。
13. 如果发现自己使用了 fixture、旧 root、旧 artifact 或无法确认 PDF 来源，必须立即返回 BLOCK，不得继续。

该固定口令的标准流程是：

```bash
python3 scripts/factorforgectl.py init-run ...
python3 scripts/factorforgectl.py run-local --report-id <report_id> --start-step 1 --end-step 1
# Humphrey 使用 OpenClaw tools.pdf 生成 Step1 primary/challenger/chief raw
python3 scripts/factorforgectl.py resume-step1 --report-id <report_id>
## Step1 完成后：汇报，等待用户明确允许继续
python3 scripts/factorforgectl.py run-local --report-id <report_id> --start-step 2 --end-step 2 --formal-llm-provider command
## Step2 完成后：汇报，等待用户明确允许继续
python3 scripts/factorforgectl.py run-local --report-id <report_id> --start-step 3a --end-step 3a
## Step3A 完成后：汇报，等待用户明确允许继续 worker dry-run
python3 scripts/factorforgectl.py check-worker --report-id <report_id> --start-step 3b --end-step 5
python3 scripts/factorforgectl.py sync-worker-artifacts --report-id <report_id> --worker-instance-id <instance_id> --artifact-sync-s3-uri <s3_uri> --dry-run
python3 scripts/factorforgectl.py run-worker --report-id <report_id> --worker-instance-id <instance_id> --start-step 3b --end-step 5 --dry-run
```

固定口令的回报必须包含：

- `report_id`
- `run_id`
- `artifact_root`
- `repo_sha`
- PDF `local_path` / `sha256` / 是否为本次附件
- Step1 task packet path
- Step1 primary/challenger/chief raw path 与 provenance PASS/FAIL
- `resume-step1` status
- Step2/3A validator rc/verdict
- `runtime_context_written`
- `check-worker` verdict
- `sync-worker-artifacts --dry-run` verdict
- `run-worker --dry-run` verdict
- proof ledger path
- `BLOCK` token（如有）

当用户说：

```text
FactorForge V2 worker: <report_id>
```

Humphrey 只能对已经通过上述 dry-run 的同一个 `report_id/run_id/artifact_root`
执行真实 worker 阶段。若研究机处于 stopped，Humphrey 可以先执行
`start-worker --poll`，等待 EC2 running 且 SSM Online 后再继续。范围限定为
Step3B/4/5。真实 worker 获得用户授权后可连续执行 `3b->5`，中间不需要再等用户逐步确认。
Step6 是合法的 post-worker 研判/迭代层，但必须在 worker
Step3B/4/5 与 Step5 证据完成后，经 `run-step6` 专用入口触发；不得通过
`run-local --end-step 6` 或手工扫描 artifact 触发。

真实 worker 阶段标准流程：

```bash
python3 scripts/factorforgectl.py start-worker \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --poll

python3 scripts/factorforgectl.py sync-worker-artifacts \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --artifact-sync-s3-uri s3://<bucket>/<prefix>/<run_id>.tgz \
  --poll

python3 scripts/factorforgectl.py run-worker \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --start-step 3b \
  --end-step 5 \
  --poll
```

研究机停止规则：

- `run-worker --poll` 结束后，Humphrey 只回报 proof、SSM command id、
  Step3B/4/5 verdict、artifact path、BLOCK token（如有），不得自行 stop 或启动 Step6。
- 只有用户明确表示“验收通过，停止研究机”或等价意思后，才允许执行：

```bash
python3 scripts/factorforgectl.py stop-worker \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --after-user-acceptance \
  --poll
```

- 未带 `--after-user-acceptance` 的真实 `stop-worker` 必须 BLOCK。

初始化 run：

```bash
python3 scripts/factorforgectl.py init-run \
  --report-id <report_id> \
  --report-pdf-s3 <s3_uri> \
  --report-pdf-sha256 <sha256> \
  --report-pdf-local <local_pdf_or_manifest>
```

查询状态：

```bash
python3 scripts/factorforgectl.py status --report-id <report_id>
```

BLOCK 只读恢复：

```bash
python3 scripts/factorforgectl.py recover-block --report-id <report_id>
```

生成 proof：

```bash
python3 scripts/factorforgectl.py proof --report-id <report_id>
```

本机步骤：

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id <report_id> \
  --start-step 1 \
  --end-step 1
```

`run-local` 是严格本机状态机，只允许以下 step range：

```text
1 -> 1
2 -> 2
3a -> 3a
```

`run-local` 禁止 `--end-step 6`。Step6 不是本机 prepare 阶段；它只能在
worker Step3B/4/5 真实完成、`factor_run_master` 与 `factor_case_master`
存在后，由 `run-step6` 专用 post-worker 控制入口触发。

`run-local --start-step 1 --end-step 1` 会调用
`prepare_factorforge_formal_artifacts.py` 的 agent-tool Step1 路径，生成
Step1 task packet，并返回 `BLOCK_AGENT_TOOL_STEP1_REQUIRED`。这是正常的
OpenClaw PDF 工具断点，不是失败。

Step1 raw 写回并通过 `resume-step1` 后，必须先汇报 Step1 结果并等待用户明确允许，再继续本机 Step2：

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id <report_id> \
  --start-step 2 \
  --end-step 2 \
  --formal-llm-provider command
```

该命令只消费 active registry 指向的 artifact root 下的 Step1 raw，并调用
formal Step2 bridge。Step2 完成后必须汇报并等待用户明确允许，再继续 Step3A：

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id <report_id> \
  --start-step 3a \
  --end-step 3a
```

Step3A 会写 `objects/runtime_context/runtime_context__<report_id>.json`，但不会启动 worker。

Step1 agent-tool 断点恢复：

```bash
python3 scripts/factorforgectl.py resume-step1 \
  --report-id <report_id>
```

`resume-step1` 只接受 active registry 绑定的 artifact root 下的：

```text
objects/agent_tool_tasks/<report_id>/step1_openclaw_pdf_task_packet.json
objects/raw_llm/<report_id>/step1/step1_primary_raw.json
objects/raw_llm/<report_id>/step1/step1_challenger_raw.json
objects/raw_llm/<report_id>/step1/step1_chief_raw.json
```

三份 raw JSON 必须匹配 task packet 中的 `report_id`、`pdf_sha256`、
`prompt_hash`、`role`，并且 provenance 必须包含
`provider=openclaw_pdf_tool`、`model=google/gemini-3.1-pro-preview`、
`source_derivation=agent_tool_formal_route`、`created_at_utc`。不匹配时返回
`BLOCK_AGENT_TOOL_STEP1_RAW_INVALID`。

研究机步骤：

先做 worker readiness preflight，只读检查 active registry 与 artifact root 是否满足
worker 调度前置条件：

```bash
python3 scripts/factorforgectl.py check-worker \
  --report-id <report_id> \
  --start-step 3b \
  --end-step 5
```

`check-worker` 必须返回 `worker_preflight_ready=true`、
`worker_started=false`，并且所有 `readiness_checks[].ok=true`。它会写
proof ledger，但不会调用 SSM。

然后同步 active artifact root 到研究机。dry-run 只生成同步命令与 proof，
不上传 S3、不调用 SSM：

```bash
python3 scripts/factorforgectl.py sync-worker-artifacts \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --artifact-sync-s3-uri s3://<bucket>/<prefix>/<run_id>.tgz \
  --dry-run
```

真实同步必须指定同一个 S3 tgz URI，并建议使用 `--poll` 等待同步命令完成。
只有同步命令返回 `artifact_synced=true`，registry 中的
`worker_artifact_sync.status=PASS` 后，才允许真实 worker dispatch：

```bash
python3 scripts/factorforgectl.py sync-worker-artifacts \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --artifact-sync-s3-uri s3://<bucket>/<prefix>/<run_id>.tgz \
  --poll
```

如果未完成同步 proof，真实 `run-worker` 必须返回
`BLOCK_WORKER_ARTIFACT_SYNC_REQUIRED`，不得发送 Step3B/4/5 SSM 命令。

先做 dry-run，只生成将要发给 worker 的命令、proof ledger 和 registry 状态，
不调用 SSM、不启动 worker：

```bash
python3 scripts/factorforgectl.py run-worker \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --start-step 3b \
  --end-step 5 \
  --dry-run
```

dry-run 返回 `worker_dry_run=true`、`worker_started=false`、
`ssm_command_id=null` 后，才允许去掉 `--dry-run` 执行真实 worker 调度：

```bash
python3 scripts/factorforgectl.py run-worker \
  --report-id <report_id> \
  --worker-instance-id <instance_id> \
  --start-step 3b \
  --end-step 5 \
  --poll
```

`run-worker --poll` 只有在 SSM invocation `Status=Success` 时才算完成。
成功后 registry 会进入 `WORKER_DONE/current_step=6`。如果 SSM 返回
`Failed`、`TimedOut`、`Cancelled` 等状态，控制面必须返回
`BLOCK_WORKER_COMMAND_FAILED`，不得把 worker 失败解释为 Step6 可用。
worker 完成后必须向用户汇报 Step3B/4/5 证据并等待验收。只有用户明确允许
Step6 后，才可以调用 `run-step6`。

## Step6 / 迭代研判

Step6 是研究反思与 loop controller。它会读取 Step4/5 证据，更新
economic hypothesis、math mechanism、research_iteration_master，并在
`decision=iterate` 时生成指向 Step3B 的 revision proposal / handoff。
但 Step6 的输出本身不是直接改代码的授权；Council/Step6 产生的修改必须经过
后续 human approval / child report / approved revision contract，才能回到 Step3B。

Step6 只能通过：

```bash
python3 scripts/factorforgectl.py run-step6 \
  --report-id <report_id> \
  --council-mode auto
```

或先 dry-run：

```bash
python3 scripts/factorforgectl.py run-step6 \
  --report-id <report_id> \
  --council-mode auto \
  --dry-run
```

`run-step6` 的硬前置证据全部来自 active registry 指向的当前 artifact root：

```text
objects/runtime_context/runtime_context__<report_id>.json
objects/factor_run_master/factor_run_master__<report_id>.json
objects/factor_case_master/factor_case_master__<report_id>.json
objects/validation/factor_evaluation__<report_id>.json
objects/handoff/handoff_to_step6__<report_id>.json
```

任一文件缺失、JSON 不合法、`report_id` 不匹配、active run `repo_sha`
不等于当前 HEAD，都必须返回 `BLOCK_STEP6_PRECONDITION_FAILED`。

默认 `run-step6 --council-mode auto` 会走 official wrapper
`scripts/run_factorforge_ultimate.py --start-step 6 --end-step 6`。如果 Step6
要求当前 main agent 补写 mechanism memo，会返回
`STEP6_AWAITING_MAIN_AGENT_MECHANISM_MEMO`；如果 Council 需要 agentic 结果，
会返回 `STEP6_AWAITING_COUNCIL_RESULTS`。Humphrey 必须按这些机器状态继续，
不得自行修改 Step3B、generated code、handoff 或 library。

## BLOCK 处理

如果 `factorforgectl.py` 返回：

```json
{"status": "BLOCK", "block_token": "..."}
```

Humphrey 必须停止。它只能回报 block token、reason、proof path，不得自行修补、不得 fallback、不得继续下一步。

## 最小合格回报

每次回报至少包含：

- `status`
- `report_id`
- `run_id`
- `artifact_root`
- `repo_sha`
- `proof_ledger`
- `block_token`（如有）
