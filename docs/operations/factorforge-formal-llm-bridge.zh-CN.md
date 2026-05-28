# Factor Forge Formal LLM Bridge

## 目标

正式新研报入口必须先生成 Step1/Step2 raw LLM artifacts，再由
`scripts/prepare_factorforge_formal_artifacts.py` 编译 formal artifacts 并运行
`validate_step1.py`、`validate_step2.py`、`validate_step3.py`。

`prepare_factorforge_formal_artifacts.py` 是 artifact compiler 和 validator，
不是 PDF/LLM 理解器。缺少 raw LLM outputs 时必须 BLOCK，不得用 deterministic
fallback 冒充正式抽取。

## Step1 Bridge

Step1 有两条 formal route：

- `agent_tool`：生产 OpenClaw PDF route。`prepare_factorforge_formal_artifacts.py`
  只写一个 task packet，要求 OpenClaw agent runtime 用内部 `pdf` tool
  调用 `google/gemini-3.1-pro-preview`，并把 primary/challenger/chief raw
  JSON 原样写回同一个 run root。它不要求、也不接受把 OpenClaw `pdf` tool
  伪装成 shell command。
- `command`：普通 stdin JSON -> stdout raw JSON 的外部 provider route。只适合
  已经有同步命令 wrapper 的 provider，不是 OpenClaw 内部 pdf tool route。

OpenClaw `pdf` tool 是 agent runtime 内部工具，不是独立 CLI。缺少 Step1 raw
时，`agent_tool` route 会返回：

```text
BLOCK_AGENT_TOOL_STEP1_REQUIRED
```

并写入：

```text
<factorforge_root>/objects/agent_tool_tasks/<report_id>/step1_openclaw_pdf_task_packet.json
```

该 task packet 是下一步给 OpenClaw agent 执行的唯一输入。agent 写回 raw 后，
再次运行 `prepare_factorforge_formal_artifacts.py` 编译/validate；compiler
不会在进程内调用真实 pdf tool。

```bash
python3 scripts/run_factorforge_step1_llm_bridge.py \
  --report-id <report_id> \
  --report-pdf <local_pdf_or_local_manifest_json> \
  --out-dir <factorforge_root>/objects/raw_llm/<report_id>/step1 \
  --write-report
```

当前生产 provider 尚未接入时会返回：

```text
BLOCK_STEP1_LLM_PROVIDER_UNAVAILABLE
```

外部 provider 生产接入可以使用通用 command provider：

```bash
FACTORFORGE_STEP1_LLM_COMMAND='your-step1-provider-command' \
python3 scripts/run_factorforge_step1_llm_bridge.py \
  --report-id <report_id> \
  --report-pdf <pdf_or_local_manifest> \
  --out-dir <factorforge_root>/objects/raw_llm/<report_id>/step1 \
  --provider command \
  --write-report
```

bridge 会把 role、PDF 路径、PDF sha256、prompt、prompt_hash、prior_outputs
作为 JSON 写入 provider command 的 stdin。provider contract：

- stdout 必须只输出可解析 raw JSON；
- stderr 只用于诊断日志；
- 非 0 退出码必须被 bridge 记录为 BLOCK；
- bridge 必须把 stdout raw output 原样落盘；
- bridge report 必须记录 raw response hash、prompt hash、provider/model/temperature、PDF sha256 和 parsed JSON validation status；
- 如果 stdout 不是可解析 JSON，bridge 必须写 `verdict=BLOCK` 的 bridge report，记录已落盘 raw output 的 hash 和 parse error；
- bridge 不做 deterministic 修补。

测试 smoke 可显式使用：

```bash
--provider fixture
```

fixture 只写 smoke raw outputs，并在 report 中标记 `provider=fixture`、
`fixture_only=true`、`formal_llm_extraction=false`。它不是生产抽取。

## Step2 Bridge

```bash
python3 scripts/run_factorforge_step2_llm_bridge.py \
  --report-id <report_id> \
  --factorforge-root <factorforge_root> \
  --out-dir <factorforge_root>/objects/raw_llm/<report_id>/step2 \
  --write-report
```

当前生产 provider 尚未接入时会返回：

```text
BLOCK_STEP2_LLM_PROVIDER_UNAVAILABLE
```

生产接入可以使用通用 command provider：

```bash
FACTORFORGE_STEP2_LLM_COMMAND='your-step2-provider-command' \
python3 scripts/run_factorforge_step2_llm_bridge.py \
  --report-id <report_id> \
  --factorforge-root <factorforge_root> \
  --out-dir <factorforge_root>/objects/raw_llm/<report_id>/step2 \
  --provider command \
  --write-report
```

bridge 会把 Step1 context、role、prompt、prompt_hash 和 prior_outputs 作为 JSON
写入 provider command 的 stdin。provider contract：

- stdout 必须只输出 primary/challenger/auditor 对应 schema 的可解析 raw JSON；
- stderr 只用于诊断日志；
- 非 0 退出码必须被 bridge 记录为 BLOCK；
- bridge 必须把 stdout raw output 原样落盘；
- bridge report 必须记录 raw response hash、prompt hash、provider/model/temperature、Step1 context hash 和 parsed JSON validation status；
- 如果 stdout 不是可解析 JSON，bridge 必须写 `verdict=BLOCK` 的 bridge report，记录已落盘 raw output 的 hash 和 parse error；
- bridge 不做 deterministic 修补。

fixture provider 和 command provider 都必须已有
`objects/raw_llm/<report_id>/step1` 下的 Step1 raw outputs。`alpha_idea_master`
只能作为附加上下文，不能替代 Step1 raw provenance。否则返回：

```text
BLOCK_STEP2_STEP1_CONTEXT_REQUIRED
```

## Compiler

正式编译入口：

```bash
python3 scripts/prepare_factorforge_formal_artifacts.py \
  --factorforge-root <factorforge_root> \
  --report-id <report_id> \
  --report-pdf <pdf> \
  --step1-primary-raw objects/raw_llm/<report_id>/step1/step1_primary_raw.json \
  --step1-challenger-raw objects/raw_llm/<report_id>/step1/step1_challenger_raw.json \
  --step1-chief-raw objects/raw_llm/<report_id>/step1/step1_chief_raw.json \
  --step2-primary-raw objects/raw_llm/<report_id>/step2/step2_primary_raw.json \
  --step2-challenger-raw objects/raw_llm/<report_id>/step2/step2_challenger_raw.json \
  --step2-auditor-raw objects/raw_llm/<report_id>/step2/step2_auditor_raw.json \
  --end-step 3a \
  --write-report
```

该入口不创建 `objects/runtime_context/`，也不启动 worker。prepare report 中：

```json
{
  "formal_artifacts_valid": true,
  "workflow_may_dispatch_worker": true,
  "worker_started": false,
  "worker_dispatch_status": "not_dispatched_by_prepare"
}
```

`worker_dispatch_allowed` 暂时保留为 legacy alias，语义等同于
`workflow_may_dispatch_worker`：只表示 validator 通过后“上层 workflow 可以继续”，
不是 prepare 脚本已经 dispatch worker。

## Local Smoke

```bash
python3 scripts/run_factorforge_formal_llm_bridge_smoke.py \
  --fresh \
  --root /tmp/factorforge_formal_llm_bridge_smoke
```

该 smoke 覆盖：

- no raw artifacts -> `BLOCK_FORMAL_STEP1_LLM_OUTPUT_REQUIRED`
- agent_tool Step1 no raw -> `BLOCK_AGENT_TOOL_STEP1_REQUIRED`，只写
  `objects/agent_tool_tasks/<report_id>/step1_openclaw_pdf_task_packet.json`
- Step1 provider missing -> `BLOCK_STEP1_LLM_PROVIDER_UNAVAILABLE`
- Step1 fixture raw outputs 可解析并记录 prompt/model/pdf sha256 provenance
- Step2 provider missing -> `BLOCK_STEP2_LLM_PROVIDER_UNAVAILABLE`
- Step2 fixture raw outputs 可解析
- fixture raw outputs 经 compiler 生成 Step1/2/3A formal artifacts
- `validate_step1.py`、`validate_step2.py`、`validate_step3.py` 全 PASS
- `worker_started=false`
- `worker_dispatch_status=not_dispatched_by_prepare`
- 不生成 runtime_context，不启动 worker
