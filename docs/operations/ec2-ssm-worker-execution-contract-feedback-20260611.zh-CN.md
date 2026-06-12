# EC2 / SSM worker execution contract feedback

日期：2026-06-11

反馈对象：OpenClaw / Factor Forge / Data API 架构师

适用范围：所有需要通过 AWS SSM 操作 EC2 / research worker / OpenClaw worker 的任务。包括但不限于 Factor Forge production proof、Data API backfill、worker sync、installed skill sync、smoke、long-running job、远程日志检查。

## 1. 结论

SSM 问题不是某个因子、某个 skill 或某个 thread 的局部问题，而是跨项目的远程执行基础设施问题。

当前实际使用中，SSM 经常被当成业务执行层：研究员在本地拼长 shell、inline Python、heredoc、远端路径和环境变量，然后通过 SSM 发到 EC2。这样会反复出现：

- shell quoting / heredoc 失败；
- stdout / stderr 截断，看不到真实错误；
- Mac repo、worker repo、OpenClaw workspace 路径混淆；
- system Python / conda Python / venv 包环境不一致；
- SSM command status `Success`，但业务脚本实际失败；
- 命令不可复现，无法审计；
- side effects 不清楚；
- 每个 thread / agent 重复踩同样的问题。

正确边界应该是：

```text
SSM 只作为 transport，不承载业务逻辑。
```

远程任务的业务逻辑必须由 repo 内受版本控制的 runner 执行，并通过 task spec JSON 输入，通过 worker command report 输出。

## 2. 当前反复出现的问题

### 2.1 SSM transport success 和 business success 混淆

SSM 返回 `Success` 只代表命令被远程 shell 执行完，不代表 Factor Forge / Data API / OpenClaw 任务成功。

现在经常需要人工继续判断：

- SSM status 是否成功；
- shell return code 是否成功；
- Python 脚本 return code 是否成功；
- smoke / validator verdict 是否成功；
- 业务 artifact 是否写出；
- side effects 是否越界。

这些判断应该由统一 report 固化，而不是靠研究员手动拼日志。

### 2.2 长 inline shell 不可维护

当前远程 proof 常见模式是：

```text
aws ssm send-command "... long shell / heredoc / inline python ..."
```

这会导致：

- 本地 quote 和远端 quote 双层交互；
- JSON 字符串转义复杂；
- heredoc 容易被截断或错位；
- 命令太长，review 不可读；
- 失败后无法稳定复现。

### 2.3 路径和运行面经常混淆

同一个 worker 上可能同时存在：

```text
/home/ubuntu/factorforge
/home/ubuntu/.openclaw/workspace/factorforge
/opt/factorforge/factorforge-data-api
/opt/factorforge/data-api-datamarts
```

不同任务还会区分：

- Mac repo；
- Mac installed skills；
- true worker repo；
- true worker OpenClaw workspace；
- Data API repo；
- Data API runtime datamart path。

如果没有统一 report，研究员很容易验证到错误机器、错误路径或错误 Python。

### 2.4 Python 环境不一致

历史上已经多次出现：

- `/usr/bin/python3` 缺包；
- conda Python 有包但不是 worker 默认 Python；
- worker repo 可 import，但 OpenClaw workspace 不一致；
- qlib / pandas / pyarrow 在不同 Python 下结果不同。

远程 runner 必须显式记录 Python path 和 import proof。

### 2.5 side effects 缺少标准声明

每次远程执行都应明确声明是否触碰：

- clean data；
- search worker；
- official promotion；
- production factor loop；
- long-running backfill；
- S3 write；
- worker process start/stop；
- installed skill sync。

现在这些边界经常靠研究员最终口头说明，应该写入 command report。

## 3. 目标设计

建议提供一个跨项目通用的 worker execution contract。

### 3.1 本地 task spec

本地只生成一个 JSON task spec，例如：

```json
{
  "task_id": "factorforge_v18_child_step4_probe_20260611",
  "project": "factor-forge",
  "runner": "scripts/run_factorforge_remote_task.py",
  "repo_path": "/home/ubuntu/factorforge",
  "workspace_path": "/home/ubuntu/.openclaw/workspace/factorforge",
  "python": "/usr/bin/python3",
  "git_sha_required": "0d8333d...",
  "mode": "smoke",
  "args": {
    "report_id": "...",
    "no_clean_data": true,
    "no_search_worker": true,
    "no_official_promotion": true
  },
  "expected_outputs": [
    "worker_command_report.json",
    "validator_verdict"
  ]
}
```

SSM 只负责把 task spec 上传到 worker 并调用固定 bootstrap：

```bash
python3 /opt/openclaw-worker/bin/run_task_spec.py /path/to/task_spec.json
```

### 3.2 远端受版本控制 runner

业务逻辑必须在 repo 内：

```text
scripts/run_factorforge_remote_task.py
scripts/run_data_api_remote_task.py
scripts/run_openclaw_remote_task.py
```

不要把复杂业务逻辑写在 SSM inline shell 里。

### 3.3 标准 worker command report

每次远程执行都必须写：

```json
{
  "schema_version": "worker_command_report_v1",
  "task_id": "...",
  "transport": {
    "type": "ssm",
    "command_id": "...",
    "instance_id": "...",
    "ssm_status": "Success"
  },
  "runtime": {
    "hostname": "...",
    "repo_path": "...",
    "workspace_path": "...",
    "git_sha": "...",
    "python_path": "...",
    "python_version": "...",
    "env_summary": {}
  },
  "execution": {
    "runner": "...",
    "argv": [],
    "return_code": 0,
    "started_at_utc": "...",
    "ended_at_utc": "...",
    "stdout_path": "...",
    "stderr_path": "..."
  },
  "business_result": {
    "verdict": "ACCEPT",
    "validator_verdict": "PASS",
    "blocker_token": null,
    "artifact_paths": []
  },
  "side_effects": {
    "clean_data_started": false,
    "search_worker_started": false,
    "official_promotion_written": false,
    "production_loop_started": false,
    "s3_written": false,
    "installed_skill_modified": false
  }
}
```

### 3.4 明确区分四个证明面

统一 wrapper 必须明确区分：

1. Mac repo proof；
2. Mac installed skill proof；
3. true worker repo proof；
4. true worker OpenClaw workspace proof。

报告中不能只写 “smoke passed”，必须写明在哪个路径、哪个 commit、哪个 Python 下 passed。

### 3.5 支持 dry-run / preflight

远程 runner 必须支持：

```text
--dry-run
--preflight-only
--no-side-effects
```

用于在正式 production run 前确认：

- repo SHA；
- Python import；
- data catalog；
- worker resource；
- required artifacts；
- output path writability；
- expected side effects。

## 4. 需要的 blocker token

建议引入以下标准 blocker：

```text
BLOCK_WORKER_TRANSPORT_FAILED
BLOCK_WORKER_REPO_SHA_MISMATCH
BLOCK_WORKER_PYTHON_IMPORT_FAILED
BLOCK_WORKER_PATH_MISMATCH
BLOCK_WORKER_RESOURCE_BUSY
BLOCK_WORKER_TASK_SPEC_INVALID
BLOCK_WORKER_BUSINESS_VERDICT_MISSING
BLOCK_WORKER_SIDE_EFFECT_CONTRACT_VIOLATED
```

这样可以避免 “SSM Success 但业务失败” 被误报为成功。

## 5. 对 Factor Forge 的直接收益

如果该 contract 落地，Factor Forge 研究员不再需要反复手动处理：

- true worker 路径确认；
- repo / OpenClaw workspace diff；
- Python 包环境；
- SSM quote；
- stdout/stderr 截断；
- worker 是否正在被 data 组 backfill 占用；
- smoke 到底在哪个路径上通过；
- clean/search/official side effects 是否越界。

研究员可以把时间用于：

- economic hypothesis；
- Dirac-style math mechanism；
- Council synthesis；
- child branch comparison；
- long side / IC / after-cost metrics 解释。

## 6. 推荐优先级

### P1. 通用 worker execution wrapper

提供 task spec JSON -> SSM transport -> remote runner -> command report 的统一链路。

### P1. transport success / business success 分离

所有远程任务必须同时报告：

- SSM transport status；
- shell return code；
- business verdict；
- validator verdict；
- side-effect status。

### P1. worker resource busy guard

远程 production run 前检查已有 backfill / worker process 和 CPU/MEM 占用。

### P2. repo/workspace parity checker

一键检查：

- repo SHA；
- OpenClaw workspace SHA；
- installed skills diff；
- Python import；
- required data catalog；
- qlib / Data API provider。

### P2. long-running job status registry

所有 backfill / production loop / worker task 写统一 status file，便于其他 thread 判断是否等待。

## 7. 边界

本反馈不要求立刻修改某个具体 Factor Forge 因子，也不要求重跑 production proof。

它要求的是全局执行合同：以后任何 thread 只要通过 SSM 操作 EC2，都应走同一套 task spec / remote runner / command report，不再把复杂业务逻辑塞进 inline SSM shell。

## 8. 初版实现状态

2026-06-11 已落地第一版通用执行合同：

```text
factor_factory/worker_execution.py
scripts/run_worker_task_spec.py
scripts/run_worker_task_via_ssm.py
scripts/run_worker_execution_contract_smoke.py
scripts/validate_worker_command_report.py
```

当前能力：

- 支持 `worker_task_spec_v1`。
- 远端 / 本地统一写 `worker_command_report_v1`。
- 报告区分：
  - transport；
  - runtime；
  - preflight；
  - execution；
  - business_result；
  - side_effects。
- 支持 repo SHA 检查。
- 支持 Python import proof。
- 支持 required path 检查。
- 支持 preflight-only / dry-run。
- 支持 stdout / stderr 落盘。
- 支持 business verdict 缺失时 BLOCK：

```text
BLOCK_WORKER_BUSINESS_VERDICT_MISSING
```

- 支持 side-effect contract 违约时 BLOCK：

```text
BLOCK_WORKER_SIDE_EFFECT_CONTRACT_VIOLATED
```

- 支持 SSM transport dry-run：SSM 只负责上传 task spec 并调用远端 `run_worker_task_spec.py`，不承载业务逻辑。
- 支持独立校验 `worker_command_report_v1`，明确区分 SSM transport success、shell return code、business verdict、side effects。

本地验证：

```bash
python3 scripts/run_worker_execution_contract_smoke.py
python3 -m py_compile factor_factory/worker_execution.py scripts/run_worker_task_spec.py scripts/run_worker_task_via_ssm.py scripts/run_worker_execution_contract_smoke.py scripts/validate_worker_command_report.py
```

结果：

```text
run_worker_execution_contract_smoke.py: ACCEPT
py_compile: PASS
```

当前还未做：

- 未把旧 Tushare SSM 入口迁移到新 contract。
- 未在真实 EC2 上执行新 contract。
- 未把 Factor Forge production loop 接入新 wrapper。
- 未处理仓内既有 entrypoint registry 缺口；本次新增的 worker 脚本已经登记，但全仓 entrypoint hygiene smoke 仍会因其他既有脚本未登记而 BLOCK。
