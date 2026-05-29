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

## Humphrey 禁止做什么

Humphrey 禁止：

- 自行 `find` / `grep` artifact root 来判断状态。
- 自行扫描 `/tmp`、workspace 顶层 `objects`、旧 archive root。
- 自行列 S3 tgz 并把旧 snapshot 当作当前 run 证据。
- 自行查询 SSM history 后拼接运行结论。
- 将 worker `stopped` 解释为 run 失败。
- 用同 report_id 的旧 artifact 替代 active registry 指向的 root。
- 手工 patch raw LLM artifact。

## 标准命令

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

生成 proof：

```bash
python3 scripts/factorforgectl.py proof --report-id <report_id>
```

本机步骤：

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id <report_id> \
  --start-step 1 \
  --end-step 3a
```

`run-local --start-step 1 --end-step 1` 会调用
`prepare_factorforge_formal_artifacts.py` 的 agent-tool Step1 路径，生成
Step1 task packet，并返回 `BLOCK_AGENT_TOOL_STEP1_REQUIRED`。这是正常的
OpenClaw PDF 工具断点，不是失败。

Step1 raw 写回并通过 `resume-step1` 后，继续本机 Step2/3A：

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id <report_id> \
  --start-step 2 \
  --end-step 3a \
  --formal-llm-provider command
```

该命令只消费 active registry 指向的 artifact root 下的 Step1 raw，并调用
formal Step2 bridge 与 Step3A。`--end-step 3a` 会写
`objects/runtime_context/runtime_context__<report_id>.json`，但不会启动 worker。

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
