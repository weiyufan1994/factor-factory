# Factor Forge Datamart / State Reuse 合同改造任务说明书

日期：2026-06-16

执行对象：Factor Factory coder thread

审查对象：Factor Forge reviewer thread

架构依据：

- `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-datamart-reuse-contract-architecture-20260616.zh-CN.md`
- `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-skill-feedback-datamart-reuse-contract-20260616.zh-CN.md`
- `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`

目标：把 datamart / state reuse 变成 Factor Forge 的显式合同。Factor law 必须声明 state dependency；Step3 必须 catalog-first 解析；缺 state 必须写 `data_request_v1` 并 BLOCK；Step4 production 禁止 full-window raw minute 临时扫描；Step6 / Council 必须输出 revision data plan。

## 0. 执行边界

请在干净分支或新 git worktree 中实现。不要在 dirty research worktree 中直接 `git add .`。

不要做：

```text
不要启动 production research
不要启动 worker
不要跑正式 Step3B / Step4 / Step6
不要生产或回填真实 Data API datamart
不要修改 Data API repo
不要迁移历史 data/ 或 knowledge/
不要把 alpha score / composite research feature 推入 Data API P0 schema
不要覆盖当前已有 dirty research 目录
```

允许做：

```text
新增 framework contract 模块
新增 fake catalog / validator / smoke
修改 Step3 / Step4 / Step6 / Ultimate 的 dry-run guard
修改 skill 文档
使用 /tmp 或临时 factor workspace 运行 smoke
```

## 1. 预期新增文件

建议新增：

```text
factor_factory/state_reuse.py
scripts/validate_factorforge_state_dependency.py
scripts/run_factorforge_state_reuse_contract_smoke.py
```

如现有模块已有更合适位置，可沿用现有 pattern，但必须保持职责清晰。

## 2. 预期修改文件

至少检查并按需修改：

```text
scripts/run_factorforge_ultimate.py
scripts/build_factorforge_runtime_context.py
factor_factory/runtime_context.py
skills/factor-forge-ultimate/SKILL.md
skills/factor-forge-step3/SKILL.md
skills/factor-forge-step4/SKILL.md
skills/factor-forge-step6/SKILL.md
skills/factor-forge-researcher/SKILL.md
```

如 Step4 具体 runner / adapter 有 raw minute input path guard，也应同步修改。

## 3. Task A：新增 state reuse contract 模块

文件：

```text
factor_factory/state_reuse.py
```

实现建议：

```python
def load_state_dependency_contract(path: Path) -> dict[str, Any]:
    ...

def validate_state_dependency_contract(contract: dict[str, Any]) -> list[str]:
    ...

def resolve_state_dependencies(
    *,
    contract: dict[str, Any],
    catalog: dict[str, Any],
    report_id: str,
    factor_id: str | None,
    research_id: str | None,
) -> dict[str, Any]:
    ...

def build_data_request(
    *,
    missing_dataset: dict[str, Any],
    report_id: str,
    factor_id: str | None,
    research_id: str | None,
) -> dict[str, Any]:
    ...

def assert_no_raw_minute_full_window_scan(
    *,
    input_paths: list[Path | str],
    production: bool,
    explicit_data_production_context: bool = False,
) -> None:
    ...
```

Contract versions：

```text
factorforge_state_dependency_contract_v1
factorforge_state_resolution_v1
factorforge_data_request_v1
factorforge_state_datamart_reuse_v1
factorforge_revision_data_plan_v1
```

## 4. Task B：Dependency contract validator CLI

文件：

```text
scripts/validate_factorforge_state_dependency.py
```

CLI：

```bash
python3 scripts/validate_factorforge_state_dependency.py \
  --dependency-contract <path> \
  --catalog <path> \
  --report-id <report_id> \
  --factor-id <factor_id> \
  --research-id <research_id> \
  --output-state-resolution <path> \
  --output-data-request-dir <path>
```

行为：

1. 读取 `state_dependency_contract`。
2. 读取 fake catalog / local catalog JSON。
3. 检查 dataset existence、schema、fields、coverage、QA、lookahead policy。
4. 写 `state_resolution_v1`。
5. 缺失或不合格时写 `data_request_v1`，退出非 0，打印 blocker token。

## 5. Task C：Step3 integration

Step3 必须在正式执行前解析 state dependency：

1. 从 executable law / child spec / runtime manifest 找到 `state_dependency_contract`。
2. 找不到时 BLOCK：

```text
BLOCK_FACTORFORGE_STATE_DEPENDENCY_UNDECLARED
```

3. 调用 resolver 写：

```text
objects/data_prep_master/<report_id>/state_resolution__<report_id>.json
objects/data_prep_master/<report_id>/data_request__*.json
```

4. 只要 `state_resolution.blocked=true`，Step3 formal outcome 必须是 blocked / awaiting data request，不允许进入 Step4 production。

## 6. Task D：Step4 raw minute guard 与 provenance

Step4 production 入口必须要求：

```text
state_resolution_path exists
state_resolution.blocked == false
all reuse_hits.qa_verdict == ACCEPT
raw_minute_full_window_scan == false
```

新增或更新 Step4 output metadata：

```json
{
  "state_datamart_reuse": {
    "contract_version": "factorforge_state_datamart_reuse_v1",
    "state_resolution_path": "...",
    "reuse_hit": true,
    "datasets": [],
    "raw_minute_full_window_scan": false,
    "bounded_smoke": false
  }
}
```

如果 Step4 production 输入路径来自 raw minute root，必须 BLOCK：

```text
BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN
```

注意：bounded smoke 可以读小样本 raw minute fixture，但 metadata 必须写 `bounded_smoke=true`，并且不能标记为 full-window production proof。

## 7. Task E：Step6 / Council revision data plan

Council synthesis、multibranch synthesis、child executable revision spec 必须包含：

```json
{
  "revision_data_plan": {
    "contract_version": "factorforge_revision_data_plan_v1",
    "reuse_existing_state": true,
    "new_state_required": false,
    "data_request_required": false,
    "portfolio_only_revision": false,
    "factor_value_recompute_required": true,
    "required_datasets": [],
    "new_state_candidates": [],
    "raw_minute_full_window_allowed": false,
    "reason": "..."
  }
}
```

Validator 规则：

1. 缺 `revision_data_plan` BLOCK。
2. `new_state_required=true` 且 `data_request_required=false` BLOCK。
3. `portfolio_only_revision=true` 时 `factor_value_recompute_required` 应为 false，除非给出 explicit override reason。
4. `raw_minute_full_window_allowed=true` 默认 BLOCK，除非处于 Data API production request 上下文。

## 8. Task F：Ultimate gate

`scripts/run_factorforge_ultimate.py` 在 Step4 前增加 gate：

1. formal run 必须有 state dependency contract。
2. formal run 必须有 state resolution。
3. blocked state resolution 不得进入 Step4。
4. missing / QA not accepted / coverage insufficient / schema mismatch 必须输出明确 blocker token。
5. dry-run 也要验证 mismatch / missing contract 的 blocker 行为。

Ultimate 对缺 state 的 outcome 建议为：

```text
awaiting_data_api_request
```

不要把它写成 research failure。

## 9. Task G：Skill 文档更新

更新：

```text
skills/factor-forge-ultimate/SKILL.md
skills/factor-forge-step3/SKILL.md
skills/factor-forge-step4/SKILL.md
skills/factor-forge-step6/SKILL.md
skills/factor-forge-researcher/SKILL.md
```

必须写明：

- Factor law 必须声明 state dependency；
- Step3 catalog-first；
- Step4 production raw minute full-window forbidden；
- 缺 datamart 写 `data_request_v1`；
- Council 必须输出 revision data plan；
- bounded smoke 不等于 production proof；
- Data API P0 schema 不接收 alpha score / composite research feature。

## 10. Blocker tokens

必须覆盖：

```text
BLOCK_FACTORFORGE_STATE_DEPENDENCY_UNDECLARED
BLOCK_FACTORFORGE_STATE_RESOLUTION_MISSING
BLOCK_FACTORFORGE_STATE_DATAMART_MISSING
BLOCK_FACTORFORGE_STATE_DATAMART_QA_NOT_ACCEPTED
BLOCK_FACTORFORGE_STATE_SCHEMA_VERSION_MISMATCH
BLOCK_FACTORFORGE_STATE_COVERAGE_INSUFFICIENT
BLOCK_FACTORFORGE_STATE_LOOKAHEAD_CONTRACT_MISSING
BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED
BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN
BLOCK_FACTORFORGE_STATE_REUSE_PROVENANCE_MISSING
```

## 11. Smoke 要求

新增：

```text
scripts/run_factorforge_state_reuse_contract_smoke.py
```

必须覆盖：

1. `state_reuse_hit_smoke`
   - fake catalog 有 `intraday_flow_state_v2`；
   - QA ACCEPT；
   - Step3 resolution PASS；
   - Step4 provenance raw scan false。

2. `state_missing_data_request_smoke`
   - fake catalog 缺 `moneyflow_xxx_state_v1`；
   - 写 `data_request_v1`；
   - BLOCK `BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED` 或 `BLOCK_FACTORFORGE_STATE_DATAMART_MISSING`；
   - 不进入 Step4 production。

3. `raw_minute_forbidden_smoke`
   - production Step4 输入 raw minute root；
   - BLOCK `BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN`。

4. `portfolio_only_revision_smoke`
   - revision data plan 标记 portfolio-only；
   - 不触发 factor value recompute。

5. `schema_coverage_negative_smoke`
   - dataset 存在但 schema / coverage 不满足；
   - 分别 BLOCK schema / coverage token。

## 12. 验证命令

完成后至少运行：

```bash
python3 -m py_compile \
  factor_factory/state_reuse.py \
  scripts/validate_factorforge_state_dependency.py \
  scripts/run_factorforge_state_reuse_contract_smoke.py

python3 scripts/run_factorforge_state_reuse_contract_smoke.py
python3 scripts/run_factor_research_workspace_smoke.py
python3 scripts/run_factorforge_knowledge_write_guard_smoke.py
git diff --check
```

如修改 Step4 / Ultimate 脚本，也要跑相关 existing smoke。

## 13. Reviewer packet 要求

提交 review 时必须说明：

```text
Branch:
Commit:
Worktree:

Scope:
- state dependency contract
- Step3 state resolution
- data_request_v1 on missing
- Step4 raw minute production guard
- Step6 revision data plan
- skill docs

Verification:
- py_compile
- run_factorforge_state_reuse_contract_smoke.py
- existing workspace / knowledge guard smoke
- git diff --check

Boundary:
- 未启动 production research
- 未启动 worker
- 未跑正式 Step3B / Step4 / Step6
- 未生产真实 Data API datamart
- 未清理历史 data/ 或 knowledge/
- 未迁移 dirty research 目录
```

## 14. 注意事项

1. 不要用真实 Data API / S3 作为 smoke 前提。先用 fake catalog 证明 framework contract。
2. 不要把 Step4 guard 写成只能识别某一个路径字符串；应抽象识别 raw minute root / production context。
3. 不要让 missing datamart fallback 到 raw minute。
4. 不要把 `data_request_v1` 当作失败；它是 awaiting data 的正式 outcome。
5. 不要把 Data API 生产优化任务混进本 PR。那是数据组任务。
