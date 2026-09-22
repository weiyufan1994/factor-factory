# Factor Forge OpenClaw Runtime V2 架构书

## 1. 背景与结论

当前问题不是 Step1-6 本身不能运行，也不是 OpenClaw 不能在 EC2 上调用研究机。问题在于旧链路把多个职责混在 Humphrey / OpenClaw agent 里：

- 解析用户意图
- 选择 artifact root
- 判断当前 run
- 查询 SSM
- 解释 worker 状态
- 查找旧 S3 包
- 判断 Step 是否 PASS/BLOCK
- 继续下一步

这些职责不应该由聊天 agent 自由执行。聊天 agent 有研究和交互价值，但它不应该成为生产状态事实源。

V2 架构的核心结论：

```text
Humphrey/OpenClaw 只做入口和工具宿主。
Factor Forge CLI 做唯一调度层。
Step1-6 保持独立。
Run identity、artifact root、SSM、validator、proof ledger 全部由确定性代码管理。
```

## 2. 目标

V2 需要达成：

1. 一个报告对应一个明确 active run。
2. 每个 run 有唯一 `run_id` 和唯一 `artifact_root`。
3. Step1-6 仍然独立，但只能消费上一步在同一个 run 下产出的 artifact。
4. Humphrey 不再扫描 `/tmp`、S3、workspace，也不再判断 worker 成败。
5. Worker 只跑计算密集段：Step3B、Step4、Step5。
6. OpenClaw EC2 负责 Step1、Step2、Step3A、Step6，以及总调度。
7. 每一步的结果都写入 proof ledger。
8. 任何不满足条件的状态都返回明确 BLOCK token。
9. 没有 fallback 到旧 root、旧 S3 snapshot、旧 SSM history 的路径。

## 3. 非目标

V2 不做这些事：

- 不重写 Step1-6 的研究逻辑。
- 不把所有 Step 合并成一个大脚本。
- 不让 Humphrey 直接运行任意 shell 命令判断状态。
- 不删除旧生产目录；旧目录只归档。
- 不依赖 `/tmp` 作为生产 artifact root。
- 不用 cron 推动主流程。
- 不把 S3 artifact tgz 当作当前 run 事实源，除非 registry 明确指向它。

## 4. 角色边界

### 4.1 用户

用户只下达业务意图：

```text
用 Factor Forge 跑这份研报
继续 RTA-31 到 Step4
复核当前 run
进入 Step5/6
```

用户不需要提供旧 root、旧 SSM command id 或历史路径。

### 4.2 Humphrey / OpenClaw

Humphrey 只允许做三件事：

1. 接收用户消息。
2. 调用固定 CLI：

```bash
python3 scripts/factorforgectl.py <command> ...
```

3. 将 CLI 输出的 JSON 摘要转述给用户。

Humphrey 禁止做：

- `find /tmp`
- `grep artifact`
- 自行查询 S3 artifact 包并解释状态
- 自行查询 SSM history 并拼结论
- 自行决定 worker stopped 是否代表失败
- 自行 fallback 到旧 artifact root
- 自行修改 raw artifact

### 4.3 factorforgectl.py

`factorforgectl.py` 是唯一调度层。它负责：

- 创建 run
- 读取 active run registry
- 分配 artifact root
- 调用 Step1-6 脚本
- 调用 worker SSM
- 轮询 worker command
- 跑 validator
- 写 proof ledger
- 返回结构化 JSON

它不负责研究判断，不替代 LLM。

### 4.4 Step skills

Step skills 继续负责研究和生成：

- Step1：读研报，生成 `alpha_idea_master`
- Step2：生成 `factor_spec_master`
- Step3A：生成数据合同和本地输入
- Step3B：生成/执行因子代码
- Step4：执行评估 backends
- Step5：归档和 case close
- Step6：研究复盘、是否迭代/晋升/拒绝

### 4.5 Research Worker EC2

研究机只负责计算：

- Step3B
- Step4
- Step5

研究机不负责 Step1 PDF reading，也不负责 Step6 研究总结。

## 5. 部署拓扑

```text
Mac local repo
  /Users/humphrey/projects/factor-factory
  source of reviewed code

OpenClaw EC2
  /home/ubuntu/.openclaw/workspace/factor-factory-production-v2
  runs factorforgectl.py
  hosts OpenClaw PDF tool / LLM interaction
  owns active_run_registry

Research Worker EC2
  /opt/factorforge/factor-factory-production
  runs Step3B/4/5 via SSM
  reads/writes the same formal artifact root

Production artifact archive
  /var/lib/factorforge/artifacts/<report_id>/<run_id>
```

旧路径只归档：

```text
/home/ubuntu/.openclaw/workspace/archive/factor-factory-production-legacy-<timestamp>
/home/ubuntu/.openclaw/workspace/archive/factor-forge-skills-legacy-<timestamp>
```

## 6. 核心数据结构

### 6.1 active_run_registry.json

位置：

```text
/var/lib/factorforge/registry/active_run_registry.json
```

结构：

```json
{
  "registry_version": "factorforge_active_run_registry_v2",
  "updated_at_utc": "2026-05-29T01:40:00Z",
  "active_runs": {
    "kaiyuan_smart_money_RTA_31": {
      "report_id": "kaiyuan_smart_money_RTA_31",
      "run_id": "20260529T014000Z_kaiyuan_smart_money_RTA_31_5f02b7a0",
      "artifact_root": "/var/lib/factorforge/artifacts/kaiyuan_smart_money_RTA_31/20260529T014000Z_kaiyuan_smart_money_RTA_31_5f02b7a0",
      "repo_sha": "af203a9e9f4000c73c62eb4a3785fa3a73b2510b",
      "report_pdf": {
        "s3_uri": "s3://yufan-data-lake/reports/kaiyuan_smart_money_RTA_31.pdf",
        "sha256": "..."
      },
      "providers": {
        "step1": {
          "provider": "openclaw_pdf_tool",
          "model": "google/gemini-3.1-pro-preview"
        },
        "step2": {
          "provider": "deepseek",
          "model": "deepseek-chat"
        },
        "step6": {
          "provider": "openclaw",
          "model": "configured-agent-model"
        }
      },
      "current_step": "step2",
      "status": "RUNNING",
      "steps": {
        "step1": {
          "status": "PASS",
          "validator_rc": 0,
          "validator_verdict": "PASS",
          "started_at_utc": "...",
          "finished_at_utc": "...",
          "outputs": {
            "alpha_idea_master": "/var/lib/factorforge/artifacts/.../objects/alpha_idea_master/alpha_idea_master__kaiyuan_smart_money_RTA_31.json"
          }
        },
        "step2": {
          "status": "PENDING"
        }
      }
    }
  }
}
```

### 6.2 formal_run_manifest.json

每个 artifact root 必须有：

```text
<artifact_root>/formal_run_manifest.json
```

最小字段：

```json
{
  "manifest_version": "factorforge_formal_run_manifest_v2",
  "report_id": "kaiyuan_smart_money_RTA_31",
  "run_id": "20260529T014000Z_kaiyuan_smart_money_RTA_31_5f02b7a0",
  "artifact_root": "/var/lib/factorforge/artifacts/kaiyuan_smart_money_RTA_31/20260529T014000Z_kaiyuan_smart_money_RTA_31_5f02b7a0",
  "repo_sha": "af203a9e9f4000c73c62eb4a3785fa3a73b2510b",
  "report_pdf_sha256": "...",
  "created_at_utc": "2026-05-29T01:40:00Z",
  "steps": {
    "step1": {
      "provider": "openclaw_pdf_tool",
      "model": "google/gemini-3.1-pro-preview"
    },
    "step2": {
      "provider": "deepseek",
      "model": "deepseek-chat"
    }
  }
}
```

### 6.3 proof_ledger.json

位置：

```text
<artifact_root>/objects/proof/proof_ledger__<report_id>.json
```

结构：

```json
{
  "proof_ledger_version": "factorforge_proof_ledger_v2",
  "report_id": "kaiyuan_smart_money_RTA_31",
  "run_id": "20260529T014000Z_kaiyuan_smart_money_RTA_31_5f02b7a0",
  "artifact_root": "/var/lib/factorforge/artifacts/...",
  "repo_sha": "af203a9e9f4000c73c62eb4a3785fa3a73b2510b",
  "status": "PASS",
  "block_token": null,
  "created_at_utc": "2026-05-29T02:30:00Z",
  "steps": {
    "step1": {
      "status": "PASS",
      "validator_rc": 0,
      "validator_verdict": "PASS",
      "raw_outputs": [
        "objects/raw_llm/.../step1_primary_raw.json",
        "objects/raw_llm/.../step1_challenger_raw.json",
        "objects/raw_llm/.../step1_chief_raw.json"
      ],
      "canonical_output": "objects/alpha_idea_master/alpha_idea_master__kaiyuan_smart_money_RTA_31.json"
    },
    "step2": {
      "status": "PASS",
      "validator_rc": 0,
      "canonical_output": "objects/factor_spec_master/factor_spec_master__kaiyuan_smart_money_RTA_31.json"
    },
    "step3a": {
      "status": "PASS",
      "validator_rc": 0,
      "canonical_output": "objects/data_prep_master/data_prep_master__kaiyuan_smart_money_RTA_31.json"
    },
    "step3b": {
      "status": "PASS",
      "worker_instance_id": "i-02cc0b6e93856fbb4",
      "ssm_command_id": "...",
      "validator_rc": 0
    },
    "step4": {
      "status": "PASS",
      "factor_values_parquet": "runs/.../factor_values__kaiyuan_smart_money_RTA_31.parquet",
      "self_quant_status": "success",
      "qlib_backtest_status": "skipped",
      "qlib_skipped_reason": "no usable qlib provider uri exists for native qlib backend"
    }
  }
}
```

## 7. 调度状态机

### 7.1 总体状态

Run 状态：

```text
CREATED
RUNNING
BLOCK
PASS
SUPERSEDED
ARCHIVED
```

Step 状态：

```text
PENDING
RUNNING
PASS
WARN
BLOCK
FAILED
SKIPPED
```

`WARN` 是否允许继续由 step policy 决定。例如 Step1 的人工复核 warning 可以继续，但必须写入 proof ledger。

### 7.2 run-all 状态机

```text
load active_run_registry
assert report_id exists
assert artifact_root allowed
assert formal_run_manifest identity matches registry

for step in requested range:
  if step status is PASS and outputs still exist:
    continue
  if step status is BLOCK:
    stop unless --resume-after-fix is provided
  run step
  validate step
  if validator PASS or allowed WARN:
    mark step PASS/WARN
    write proof ledger
    continue
  else:
    mark run BLOCK
    write block_token
    write proof ledger
    stdout JSON
    stop

mark run PASS when final requested step passes
stdout JSON
```

### 7.3 Step readiness

进入下一步必须满足：

1. 上一步 canonical output 存在。
2. 上一步 validator rc 为 0。
3. output identity 匹配当前 run：
   - `report_id`
   - `run_id`
   - `artifact_root`
   - `repo_sha`
4. proof ledger 已写入。

否则 BLOCK。

## 8. Step1-6 调度细节

### 8.1 Step1

运行位置：OpenClaw EC2。

输入：

- report PDF S3 URI 或本地路径
- Step1 provider/model
- active run identity

执行：

```text
OpenClaw pdf tool 读取 PDF
LLM 生成 primary/challenger/chief raw
standardize 成 alpha_idea_master
validate_step1
```

输出：

```text
objects/raw_llm/<report_id>/step1/step1_primary_raw.json
objects/raw_llm/<report_id>/step1/step1_challenger_raw.json
objects/raw_llm/<report_id>/step1/step1_chief_raw.json
objects/alpha_idea_master/alpha_idea_master__<report_id>.json
objects/validation/validate_step1__<report_id>.json
```

关键要求：

- raw 必须包含 provider/model/provenance。
- 不允许手工 patch raw。
- 不允许使用旧 Step1 raw。
- 不允许写 `/tmp` formal root。

### 8.2 Step2

运行位置：OpenClaw EC2。

输入：

- 当前 run 的 `alpha_idea_master`

执行：

```text
run_step2.py
validate_step2.py
```

输出：

```text
objects/factor_spec_master/factor_spec_master__<report_id>.json
objects/handoff/handoff_to_step3__<report_id>.json
objects/validation/validate_step2__<report_id>.json
```

关键要求：

- Step2 必须保留 Step1 的经济假设、数学假设、target statistic、failure modes。
- `implementation_mode`、`code_contract` 等字段必须 schema-valid。

### 8.3 Step3A

运行位置：OpenClaw EC2。

输入：

- 当前 run 的 `factor_spec_master`

执行：

```text
run_step3.py
validate_step3.py
```

输出：

```text
objects/data_prep_master/data_prep_master__<report_id>.json
objects/handoff/handoff_to_step4__<report_id>.json
runs/<report_id>/step3a_local_inputs/*
```

关键要求：

- 如果数据不可用，必须 BLOCK，例如 `BLOCK_STEP3A_DATA_UNAVAILABLE`。
- 不允许合成 fallback 用于非 sample report。
- Data API 或本地数据源必须写入 provenance。

### 8.4 Step3B

运行位置：Research Worker EC2。

触发方式：OpenClaw EC2 上 `factorforgectl.py` 通过 SSM 发命令。

执行：

```text
run_step3b.py
validate_step3b.py
```

输出：

```text
generated_code/<report_id>/*
runs/<report_id>/factor_values__<report_id>.parquet
objects/validation/validate_step3b__<report_id>.json
```

关键要求：

- worker repo SHA 必须等于 registry repo SHA。
- worker 写入的 artifact root 必须等于 registry artifact root。
- SSM stdout/stderr 必须进入 proof ledger。
- worker stopped 只是实例状态，不等于 run failure。

### 8.5 Step4

运行位置：Research Worker EC2。

执行：

```text
run_step4.py
validate_step4.py
```

输出：

```text
objects/factor_run_master/factor_run_master__<report_id>.json
objects/validation/factor_run_validation_revision__<report_id>.json
evaluations/<report_id>/self_quant_analyzer/evaluation_payload.json
evaluations/<report_id>/qlib_backtest/evaluation_payload.json
```

关键要求：

- `factor_run_master.run_status=success` 才可进入 Step5。
- qlib skipped 是允许状态，但必须写 skipped reason。
- self_quant payload 缺失必须 BLOCK。

### 8.6 Step5

运行位置：Research Worker EC2。

执行：

```text
run_step5.py
validate_step5.py
```

输出：

```text
objects/factor_case_master/factor_case_master__<report_id>.json
objects/handoff/handoff_to_step6__<report_id>.json
objects/validation/validate_step5__<report_id>.json
```

关键要求：

- Step5 只归档和总结 Step4 证据。
- 不做 Step6 研究判断。
- 不启动 search/promotion。

### 8.7 Step6

运行位置：OpenClaw EC2。

输入：

- Step5 case master
- Step4 evidence
- prior cases / knowledge base

执行：

```text
run_step6.py
validate_step6.py
```

输出：

```text
objects/research_iteration_master/research_iteration_master__<report_id>.json
objects/validation/validate_step6__<report_id>.json
factor library / knowledge writeback artifacts
```

关键要求：

- Step6 决定 promote / iterate / reject / needs_human_review。
- 如果 iterate，只写 revision proposal，不直接改 Step3B 代码。
- 真正代码修改回到 Step3B。

## 9. SSM 调度

### 9.1 SSM command 格式

`factorforgectl.py run-worker` 生成固定命令：

```bash
set -eu
export FACTORFORGE_ROOT="<artifact_root>"
export FACTORFORGE_ACTIVE_RUN_ID="<run_id>"
export FACTORFORGE_REPORT_ID="<report_id>"
cd /opt/factorforge/factor-factory-production
test "$(git rev-parse HEAD)" = "<repo_sha>"
python3 scripts/run_factorforge_ultimate.py \
  --report-id "<report_id>" \
  --factorforge-root "$FACTORFORGE_ROOT" \
  --start-step "<start>" \
  --end-step "<end>" \
  --council-mode off
```

### 9.2 SSM polling

不使用 cron 推动主流程。

`factorforgectl.py` 内部轮询：

```text
send-command -> command_id
while status in Pending/InProgress/Delayed:
  sleep 10 seconds
  get-command-invocation
  if timeout:
    BLOCK_WORKER_SSM_TIMEOUT
if status Success and ResponseCode 0:
  read proof artifacts
else:
  BLOCK_WORKER_COMMAND_FAILED
```

### 9.3 worker stopped

worker stopped 不是失败。

规则：

- 如果只查旧 command output，worker stopped 不影响。
- 如果需要 live cat artifact，而 worker stopped，则返回：

```text
BLOCK_WORKER_STOPPED_FOR_LIVE_ARTIFACT_READ
```

- 不允许因 worker stopped 去读旧 S3 snapshot 代替 live root。

## 10. BLOCK 体系

常见 BLOCK：

```text
BLOCK_ACTIVE_RUN_NOT_FOUND
BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH
BLOCK_FORMAL_RUN_ROOT_FORBIDDEN
BLOCK_STEP1_RAW_JSON_INVALID
BLOCK_STEP1_OUTPUT_MISSING
BLOCK_STEP1_VALIDATION_FAILED
BLOCK_STEP2_SCHEMA_INVALID
BLOCK_STEP2_VALIDATION_FAILED
BLOCK_STEP3A_DATA_UNAVAILABLE
BLOCK_STEP3A_VALIDATION_FAILED
BLOCK_WORKER_REPO_SHA_MISMATCH
BLOCK_WORKER_SSM_TIMEOUT
BLOCK_WORKER_COMMAND_FAILED
BLOCK_WORKER_STOPPED_FOR_LIVE_ARTIFACT_READ
BLOCK_STEP3B_EXECUTION_FAILED
BLOCK_STEP3B_VALIDATION_FAILED
BLOCK_STEP4_FACTOR_VALUES_MISSING
BLOCK_STEP4_VALIDATION_FAILED
BLOCK_STEP5_EVALUATION_MISSING
BLOCK_STEP5_VALIDATION_FAILED
BLOCK_STEP6_VALIDATION_FAILED
```

BLOCK 时必须写：

```json
{
  "status": "BLOCK",
  "failed_step": "step3a",
  "block_token": "BLOCK_STEP3A_DATA_UNAVAILABLE",
  "reason": "...",
  "artifact_root": "...",
  "proof_ledger": "..."
}
```

## 11. Resume 规则

Resume 不靠聊天上下文。

命令：

```bash
python3 scripts/factorforgectl.py resume --report-id <report_id>
```

规则：

1. 读取 active registry。
2. 找到第一个非 PASS step。
3. 重新校验所有已 PASS step 的 outputs。
4. 如果之前 PASS 的 output 缺失或 identity 不匹配，BLOCK。
5. 如果当前 blocked step 的 blocker 已修复，继续。
6. 如果 blocker 未修复，返回同一个 BLOCK token。

## 12. 为什么不需要 cron

主流程不需要 cron。

原因：

- 本机步骤是同步 subprocess，退出即知道结果。
- worker 步骤由当前 `factorforgectl.py` 调用内有限 polling。
- 失败后写 BLOCK，等待用户/修复命令 resume。

可以有低频 watchdog，但它只能做提醒：

```text
list active registry
find RUNNING longer than threshold
report stale run
```

watchdog 禁止推进流程。

## 13. CLI 接口

### 13.1 init-run

```bash
python3 scripts/factorforgectl.py init-run \
  --report-id kaiyuan_smart_money_RTA_31 \
  --report-pdf-s3 s3://.../report.pdf \
  --step1-provider openclaw_pdf_tool \
  --step1-model google/gemini-3.1-pro-preview \
  --step2-provider deepseek \
  --step2-model deepseek-chat
```

### 13.2 run-local

```bash
python3 scripts/factorforgectl.py run-local \
  --report-id kaiyuan_smart_money_RTA_31 \
  --start-step 1 \
  --end-step 3a
```

### 13.3 run-worker

```bash
python3 scripts/factorforgectl.py run-worker \
  --report-id kaiyuan_smart_money_RTA_31 \
  --worker-instance-id i-02cc0b6e93856fbb4 \
  --start-step 3b \
  --end-step 5
```

### 13.4 run-all

```bash
python3 scripts/factorforgectl.py run-all \
  --report-id kaiyuan_smart_money_RTA_31 \
  --worker-instance-id i-02cc0b6e93856fbb4
```

### 13.5 status

```bash
python3 scripts/factorforgectl.py status --report-id kaiyuan_smart_money_RTA_31
```

### 13.6 proof

```bash
python3 scripts/factorforgectl.py proof --report-id kaiyuan_smart_money_RTA_31
```

## 14. Humphrey 调用协议

Humphrey system prompt / skill 只保留以下规则：

```text
当用户要求运行 Factor Forge：
1. 不要自行查找 artifact。
2. 不要自行调用 AWS SSM。
3. 不要自行读取 /tmp 或 S3 tgz。
4. 只调用 scripts/factorforgectl.py。
5. 将 factorforgectl stdout JSON 原样摘要给用户。
6. 如果 factorforgectl 返回 BLOCK，只报告 BLOCK，不自行修补。
```

Humphrey 可返回：

```text
Factor Forge run BLOCK:
- report_id: ...
- run_id: ...
- failed_step: ...
- block_token: ...
- proof_ledger: ...
```

或：

```text
Factor Forge run PASS:
- report_id: ...
- run_id: ...
- artifact_root: ...
- completed_steps: ...
- proof_ledger: ...
```

## 15. 迁移计划

### 15.1 Mac baseline

确认：

```bash
cd /Users/humphrey/projects/factor-factory
git status --short
git rev-parse HEAD
git diff --check
```

要求：

```text
status clean
HEAD pinned
diff check PASS
```

### 15.2 EC2 archive

旧目录只移动：

```text
/home/ubuntu/.openclaw/workspace/factor-factory-production
  -> /home/ubuntu/.openclaw/workspace/archive/factor-factory-production-legacy-<timestamp>
```

旧 skill 只移动：

```text
/home/ubuntu/.codex/skills/factor-forge-*
  -> /home/ubuntu/.openclaw/workspace/archive/factor-forge-skills-legacy-<timestamp>/
```

### 15.3 EC2 clean deploy

新目录：

```text
/home/ubuntu/.openclaw/workspace/factor-factory-production-v2
```

部署：

```bash
git clone https://github.com/weiyufan1994/factor-factory.git factor-factory-production-v2
git checkout <reviewed_sha>
```

### 15.4 Worker sync

worker repo 必须同步同一 SHA：

```text
/opt/factorforge/factor-factory-production
```

执行 Step3B/4/5 前强制检查：

```bash
git rev-parse HEAD == registry.repo_sha
git status --short == empty
```

## 16. 验收标准

V2 可接受的最低证明：

1. `factorforgectl.py` 存在并登记为唯一 OpenClaw/Humphrey production entrypoint。
2. `active_run_registry.json` 创建和读取正常。
3. `/tmp` root 被拒绝。
4. repo root 被拒绝。
5. workspace top-level artifact root 被拒绝。
6. missing report 返回 `BLOCK_ACTIVE_RUN_NOT_FOUND`。
7. root mismatch 返回 `BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH`。
8. Step1 PASS 后 registry 标记 Step1 PASS，并写 proof ledger。
9. Step2 只能消费当前 run 的 Step1 output。
10. Step3A 只能消费当前 run 的 Step2 output。
11. Worker 命令必须检查 worker repo SHA。
12. SSM stdout/stderr 进入 proof ledger。
13. worker stopped 不会导致旧 artifact fallback。
14. Humphrey 不再执行 artifact scanning。
15. 所有回报都包含 `report_id/run_id/artifact_root/repo_sha/proof_ledger`。

## 17. 风险与处理

### 17.1 OpenClaw PDF tool 不是 shell command

处理：

- Step1 在 OpenClaw runtime 内执行。
- `factorforgectl.py` 对 Step1 可以调用一个 OpenClaw-local adapter。
- adapter 只负责把 PDF tool output 写入当前 run raw path。

### 17.2 Worker 长时间运行

处理：

- SSM polling 有 timeout。
- 超时写 `BLOCK_WORKER_SSM_TIMEOUT`。
- 后续可 resume。

### 17.3 LLM 输出不稳定

处理：

- raw output 原样保存。
- standardizer 转 canonical。
- validator 决定 PASS/BLOCK。
- 不允许人工 patch raw。

### 17.4 旧 artifact 干扰

处理：

- active registry 是唯一入口。
- proof/status 命令不扫描旧 root。
- 旧 root 只能通过 explicit archive audit 命令读取，不能参与 active run。

## 18. 最终形态

用户体验应该变成：

```text
用户：跑这份报告。
Humphrey：调用 factorforgectl run-all。
factorforgectl：创建 run，跑 Step1-6，写 proof ledger。
Humphrey：返回 PASS/BLOCK 摘要。
```

而不是：

```text
Humphrey 自己查 root、查 SSM、查 S3、猜当前状态。
```

这就是 V2 的根本变化。
