# Factor Forge Console MVP 任务说明书

日期：2026-06-29

执行对象：Console coder

审查对象：Console reviewer

架构依据：

- `docs/architecture/factorforge-console-architecture-20260629.zh-CN.md`
- 当前 Miner campaign artifact：
  `/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626`

## 1. 目标

实现一个本地 Factor Forge Console MVP，让用户不用翻长 thread，就能看到：

- 当前 workspace / campaign 状态
- Miner 候选数量和筛选结论
- Data/API 缺口
- Research queue 是否有可转交 Ultimate 的候选
- task manifest / result manifest
- artifact 链接
- 边界声明

MVP 只读现有 artifact，不重写 Miner 或 Ultimate 逻辑。

## 2. 执行边界

必须在独立 worktree 执行，例如：

```text
/tmp/factorforge-console-workspace
```

禁止：

```text
不要改 Ultimate 研究逻辑
不要改 Miner candidate/cheap-screen 逻辑
不要启动 production research
不要启动 worker
不要跑 formal Step3B / Step4 / Step6
不要写 data/clean
不要写 repo-root knowledge vault
不要用 git add .
```

允许：

```text
新增 Console 只读模块
新增 Console 本地 Web UI
新增 Console task/result manifest schema
新增 smoke
读取 /tmp/factorforge-miner-workspace 下的现有 Miner campaign artifact
```

## 3. 新增文件

```text
factor_factory/console/__init__.py
factor_factory/console/models.py
factor_factory/console/discovery.py
factor_factory/console/readers.py
factor_factory/console/task_manifest.py
factor_factory/console/summary.py
factor_factory/console/static_app.py
scripts/run_factorforge_console.py
scripts/run_factorforge_console_smoke.py
tests/test_factorforge_console.py
```

## 4. 核心数据模型

### 4.1 CampaignSummary

字段：

```json
{
  "campaign_id": "",
  "workspace_root": "",
  "verdict": "ACCEPT|BLOCK|PARTIAL|UNKNOWN",
  "candidate_count": 0,
  "cheap_screen_passed": 0,
  "research_queue_count": 0,
  "data_gap_count": 0,
  "data_request_count": 0,
  "template_status_counts": {},
  "artifact_paths": {},
  "blockers": [],
  "next_actions": [],
  "boundary_statement": ""
}
```

### 4.2 ConsoleTask

字段：

```json
{
  "contract_version": "factorforge_console_task_v1",
  "task_id": "",
  "task_type": "factorforge_miner_campaign",
  "repo_root": "",
  "execution_workspace": "",
  "campaign_id": "",
  "workspace_root": "",
  "inputs": {},
  "steps": [],
  "boundaries": {},
  "expected_outputs": []
}
```

### 4.3 ConsoleResult

字段：

```json
{
  "contract_version": "factorforge_console_result_v1",
  "task_id": "",
  "run_id": "",
  "status": "completed|blocked|failed|running",
  "verdict": "ACCEPT|BLOCK|PARTIAL|UNKNOWN",
  "metrics": {},
  "artifact_paths": {},
  "blockers": [],
  "next_actions": [],
  "boundaries_observed": {}
}
```

## 5. 模块任务

### Task A：模型和 schema

文件：

```text
factor_factory/console/models.py
```

要求：

- 使用 `dataclasses`，不引入重依赖。
- 支持从 dict 构造。
- 支持输出 JSON serializable dict。
- 对 `verdict`、`contract_version` 做最小校验。

### Task B：artifact discovery

文件：

```text
factor_factory/console/discovery.py
```

要求：

- 输入一个或多个 repo/worktree root。
- 查找 `factor_research/miner/<campaign_id>/objects/miner_capability_inventory.json`。
- 返回 campaign workspace 列表。
- 忽略不完整 workspace，但记录 warning。
- 不扫描 `data/clean`。

### Task C：Miner artifact reader

文件：

```text
factor_factory/console/readers.py
```

要求读取：

```text
objects/miner_capability_inventory.json
objects/candidates/candidate_manifest.json
objects/data_gap_report.json
objects/cheap_screen/cheap_screen_summary.json
objects/research_queue/research_queue.json
```

并输出 `CampaignSummary`。

判定规则：

```text
research_queue_count > 0 -> PARTIAL 或 ACCEPT
candidate_count > 0 且 research_queue_count == 0 且 data_gap_count > 0 -> BLOCK
candidate_count == 0 -> BLOCK
artifact 缺失 -> BLOCK
cheap_screen_summary.promotion_forbidden_until_formal != true -> BLOCK
```

MVP 不把 cheap-screen 结果当 official proof。

### Task D：task/result manifest writer

文件：

```text
factor_factory/console/task_manifest.py
```

要求：

- 写 `factor_research/console/tasks/<task_id>.json`。
- 写 `factor_research/console/results/<task_id>.json`。
- 所有写入必须在 `factor_research/console/` 下。
- 如果 path 越界，抛出 `BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE`。

### Task E：summary renderer

文件：

```text
factor_factory/console/summary.py
```

要求：

- 把 `CampaignSummary` 渲染成 HTML 片段。
- 渲染 Dashboard、Campaign、Data Gap、Queue 四块。
- HTML 必须能直接用浏览器打开。
- 不要求复杂前端框架。

### Task F：本地 Console server

文件：

```text
factor_factory/console/static_app.py
scripts/run_factorforge_console.py
```

要求：

- 默认只读模式。
- 参数：

```bash
python3 scripts/run_factorforge_console.py \
  --root /tmp/factorforge-miner-workspace \
  --host 127.0.0.1 \
  --port 8765
```

- 输出本地 URL。
- 页面至少包含：
  - Dashboard
  - Campaign summary
  - Data Gap summary
  - Research Queue summary
  - artifact links

### Task G：smoke

文件：

```text
scripts/run_factorforge_console_smoke.py
```

使用当前 Miner campaign 验收：

```text
/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626
```

如果该路径不存在，smoke 应创建 `/tmp/factorforge_console_smoke` fixture。

必须断言：

```text
candidate_count == 12
research_queue_count == 0
data_gap_count == 46
data_request_count == 1
template_status_counts.needs_operator == 6
template_status_counts.partial == 4
template_status_counts.needs_data == 2
verdict == BLOCK
promotion_forbidden_until_formal == true
所有 artifact link 在 campaign workspace 下
```

## 6. 验收命令

```bash
python3 -m py_compile \
  factor_factory/console/*.py \
  scripts/run_factorforge_console.py \
  scripts/run_factorforge_console_smoke.py

python3 scripts/run_factorforge_console_smoke.py

python3 -m pytest tests/test_factorforge_console.py -q

git diff --check
```

## 7. Reviewer 要点

Reviewer 必须确认：

1. Console 没有改 Ultimate/Miner 研究逻辑。
2. Console 默认只读。
3. task/result manifest 写入只在 `factor_research/console/`。
4. 当前真实 Miner campaign 能被正确展示为 `BLOCK`。
5. Console 不把 cheap screen 结果说成 official promotion。
6. artifact link 不越界。
7. 没有启动 production research / worker / formal Step3B/Step4/Step6 / clean data mutation。

## 8. 交付物

MVP 完成后应提供：

```text
本地 URL
Console smoke 输出
主要页面截图或 HTML 路径
Campaign summary
已知限制
下一步建议
```
