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
  --report-pdf-sha256 <sha256>
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
