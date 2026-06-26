# Factor Forge Miner MVP Adapter 任务书

日期：2026-06-26

状态：给 coder / reviewer 的实现任务书

适用范围：

- `factor-forge-miner` skill
- Factor Forge Miner 候选挖矿 MVP
- 复用现有 Data API、datamart、Formula-IR / operator、Step4 评价能力

不适用范围：

- 不重写 Data API；
- 不新建大规模 production datamart；
- 不修改 `factor-forge-ultimate` 的研报直达 Step1-6 能力；
- 不启动 production research、worker、formal Step3B、Step4、Step6；
- 不处理 clean data；
- 不迁移历史 Alpha101 / factor_research 产物。

## 1. 目标

本任务不是从零建设新数据系统，而是在现有能力上加一层轻量
`Miner adapter`：

```text
已有 Data API + 已有 datamart + 已有 Formula/operator + 已有评价指标
  -> miner_capability_inventory
  -> miner_template_registry
  -> candidate_packet
  -> cheap_screen_runner
  -> research_queue
  -> Ultimate formal research
```

Miner 的目标是提高“候选因子生产和初筛”吞吐。它不负责正式因子
promotion，不负责深度机制验证，不替代 Ultimate。

## 2. 必须保留的 Ultimate 主路径

现有 Ultimate 必须继续支持：

```text
研报/PDF/券商报告/明确 source idea
  -> Step1 阅读和 author intent extraction
  -> Step2 canonical factor spec
  -> Step3 data/runtime
  -> Step4 evidence
  -> Step5 archive
  -> Step6 reflection / knowledge writeback
```

Coder 不得把“用户给研报要求研究”的请求强制改走 Miner。

路由原则：

| 用户意图 | 默认路由 |
|---|---|
| 给研报/PDF/券商报告，要求研究因子 | Ultimate Step1-6 |
| 给一个明确 source idea，要求正式研究 | Ultimate Step1-6 |
| 要批量挖候选、模板 sweep、公式变形、cheap screen | Miner |
| 要从已有研究中生成 follow-on candidate | Miner sidecar，可排队给 Ultimate |
| Miner cheap screen 通过后要正式研究 | Ultimate |

Miner 可以作为 Ultimate 的 sidecar，但不能覆盖 canonical report factor。

## 3. 当前已有能力判断

不能再把问题简单表述为“没有数据底座”。更准确的判断是：

1. Data API 已经提供 dataset / date range / universe / fields 的读取合同。
2. Data API 已经有 catalog、QA、read smoke、datamart contract 方向。
3. Factor Forge 已有 Formula-IR、operator、Step3/Step4 执行评价能力。
4. Data API 侧已有部分状态与算子模块，例如 daily technical state、
   flow distribution moments、value occupation、intraday operator kernels、
   smart money / moneyflow state 等。
5. 缺的是把这些能力组织成 Miner 专用流水线：
   - capability inventory；
   - template registry；
   - candidate packet；
   - cheap screen runner；
   - research queue；
   - data gap report。

## 4. Phase 1: Capability Inventory

新增或实现一个只读 inventory 生成器，输出当前 Miner 可复用能力。

建议路径：

```text
scripts/build_factorforge_miner_capability_inventory.py
```

建议输出到 active miner workspace：

```text
factor_research/miner/<campaign_id>/objects/miner_capability_inventory.json
factor_research/miner/<campaign_id>/docs/miner_capability_inventory.md
```

Inventory 至少包含：

```json
{
  "version": "factorforge_miner_capability_inventory_v1",
  "campaign_id": "",
  "generated_at_utc": "",
  "data_api_catalogs": [],
  "datasets": [
    {
      "dataset_id": "",
      "fields": [],
      "coverage": {},
      "qa_status": "",
      "lookahead_policy": "",
      "materialized_root": "",
      "miner_use": "direct_input|state_datamart|label_panel|control_panel|unsupported"
    }
  ],
  "operators": [
    {
      "operator_id": "",
      "source_module": "",
      "input_grain": "daily|minute|state|panel",
      "supported_for_batch_screen": true,
      "notes": ""
    }
  ],
  "template_support": [
    {
      "template_id": "",
      "support_status": "ready|partial|needs_data|needs_operator",
      "missing_datasets": [],
      "missing_operators": []
    }
  ]
}
```

原则：

- 只读 catalog / module registry / known operator registry。
- 不下载大数据，不启动 worker，不写 clean data。
- 如果 catalog 不存在，输出 `catalog_missing`，不要猜路径。
- 如果能力存在但 QA / coverage 不足，标记 partial，不要伪装 ready。

## 5. Phase 2: Miner Template Registry

新增模板注册表。它不是新算子，而是把已有数据和算子包装成可批量生产
candidate 的“配方”。

建议路径：

```text
factor_factory/miner/template_registry.py
```

或先用 JSON/YAML：

```text
factor_factory/miner/templates/miner_template_registry.json
```

MVP 模板建议至少覆盖：

| template_id | 逻辑族 | 依赖 |
|---|---|---|
| `open_gap_intraday_continuation` | 开盘过反应 / 日内延续 | daily bar / minute open-close |
| `intraday_return_skew` | 日内收益偏度 | minute bar 或 distribution moments |
| `intraday_return_kurtosis` | 日内厚尾 | minute bar 或 distribution moments |
| `realized_var_over_range` | 噪音 / sigma drag | minute OHLCV |
| `volume_weighted_range` | 单位成交带来的波动 | minute OHLCV |
| `high_location_volume_pressure` | 高位放量压力 | minute OHLCV |
| `low_location_absorption` | 低位吸收 | minute OHLCV |
| `up_down_volume_imbalance_proxy` | OHLCV flow proxy | minute OHLCV |
| `cutoff_flow_persistence` | cutoff 前资金持续 | intraday flow state |
| `value_occupation_support_overhang` | 价格轴筹码 / 支撑阻力 | value occupation state |
| `turnover_acceleration` | 换手加速度 | daily_basic / turnover |
| `residual_vol_liquidity_interaction` | 残差波动和流动性交互 | daily/state + neutralization |

每个 template 必须声明：

```json
{
  "template_id": "",
  "family": "",
  "economic_prior": "",
  "math_object": "",
  "required_datasets": [],
  "required_fields": [],
  "operator_dependencies": [],
  "parameter_grid": {},
  "expected_metric_signature": {},
  "falsification_tests": [],
  "fallback_if_missing": "needs_data|skip|proxy_allowed"
}
```

## 6. Phase 3: Candidate Packet Generator

新增候选包生成器。它只生成候选，不跑正式研究。

建议路径：

```text
scripts/build_factorforge_miner_candidates.py
```

输入：

- campaign id；
- active workspace；
- template ids；
- parameter grid；
- capability inventory。

输出：

```text
factor_research/miner/<campaign_id>/objects/candidates/candidate_packet__<candidate_id>.json
factor_research/miner/<campaign_id>/objects/candidates/candidate_manifest.json
```

每个 candidate 必须带：

- `candidate_id`
- `template_id`
- `formula_or_recipe`
- `input_datasets`
- `operator_dependencies`
- `information_set`
- `economic_prior`
- `return_source_prior`
- `payer_hypothesis`
- `math_object`
- `expected_metric_signature`
- `falsification_tests`
- `promotion_forbidden_until_formal=true`

如果 template 依赖缺失，candidate 状态应为 `needs_data` 或
`needs_operator`，并进入 data gap report，而不是强行执行。

## 7. Phase 4: Cheap Screen Runner

新增廉价筛选 runner。MVP 只要求能对 ready candidates 输出统一 summary；
不要求替代 Step4。

建议路径：

```text
scripts/run_factorforge_miner_cheap_screen.py
```

输入：

- candidate manifest；
- Data API catalog；
- screen window；
- universe；
- label policy；
- output workspace。

输出：

```text
factor_research/miner/<campaign_id>/objects/cheap_screen/cheap_screen_summary.json
factor_research/miner/<campaign_id>/objects/cheap_screen/cheap_screen_results.parquet
factor_research/miner/<campaign_id>/docs/cheap_screen_report.md
```

最低指标：

- RankIC mean；
- RankICIR；
- IC hit rate；
- group gross spread；
- long-end gross return；
- short-end gross return；
- monotonicity score；
- coverage；
- turnover estimate；
- failure reason；
- decision：
  - `discard`
  - `keep_as_feature`
  - `send_to_formal_research`
  - `needs_data`
  - `execution_research_needed`

Cheap screen 只能写：

```text
evidence_role=exploratory_evidence
promotion_forbidden_until_formal=true
```

不得写 official factor library，不得把 cheap screen 当 Step4 formal evidence。

## 8. Phase 5: Research Queue

新增 queue writer：

```text
scripts/build_factorforge_miner_research_queue.py
```

输出：

```text
factor_research/miner/<campaign_id>/objects/research_queue/research_queue.jsonl
factor_research/miner/<campaign_id>/docs/research_queue.md
```

Queue item schema：

```json
{
  "queue_item_version": "factorforge_miner_research_queue_item_v1",
  "candidate_id": "",
  "priority": "high|medium|low",
  "recommended_formal_route": "new_factor|feature_candidate|state_descriptor|execution_research",
  "formal_question": "",
  "required_datamarts": [],
  "missing_data_requests": [],
  "cheap_screen_artifacts": [],
  "overclaim_guard": "Cheap screen is exploratory and cannot support promotion."
}
```

只有 `send_to_formal_research` 才能进入 Ultimate 正式研究。

## 9. Data Gap Report

如果 Miner 发现缺数据，输出 data gap report，而不是自行生产 datamart。

输出路径：

```text
factor_research/miner/<campaign_id>/docs/data_gap_report.md
factor_research/miner/<campaign_id>/objects/data_gap_report.json
```

必须区分：

- 已有 Data API dataset 但字段缺失；
- 已有 datamart 但 QA / coverage / lookahead 不足；
- 已有 raw data 但缺 reusable state datamart；
- 缺 operator；
- 缺 label / universe / controls panel；
- 只是 template 不适合当前数据。

只有 reusable state 层缺失时，才生成 Data API request。不得每个 alpha score 都要求
Data API 建 datamart。

## 10. 验收 smoke

新增 smoke：

```text
scripts/run_factorforge_miner_mvp_smoke.py
```

Smoke 应使用 `/tmp` fixture，不读生产大表。

必须覆盖：

1. capability inventory 可在 mock catalog 上生成；
2. template registry 至少加载 10 个模板；
3. candidate generator 生成 candidate packet，并带 lineage；
4. 缺 dataset 的 template 进入 `needs_data`，不执行；
5. cheap screen 对小 fixture 输出 RankIC / group spread / monotonicity；
6. cheap screen 输出明确 `exploratory_evidence`；
7. research queue 只收 `send_to_formal_research`；
8. Ultimate skill 文件无修改；
9. 不写 repo-root factor-specific scripts / baseline Step3 runtime；
10. 不写 clean data。

验收命令建议：

```bash
python3 -m py_compile factor_factory/miner/*.py scripts/build_factorforge_miner_candidates.py scripts/run_factorforge_miner_cheap_screen.py
python3 scripts/run_factorforge_miner_mvp_smoke.py
git diff --check
```

## 11. Blocker Tokens

建议新增：

```text
BLOCK_FACTORFORGE_MINER_WORKSPACE_MISSING
BLOCK_FACTORFORGE_MINER_TEMPLATE_REGISTRY_INVALID
BLOCK_FACTORFORGE_MINER_CANDIDATE_PACKET_INVALID
BLOCK_FACTORFORGE_MINER_CAPABILITY_INVENTORY_MISSING
BLOCK_FACTORFORGE_MINER_CHEAP_SCREEN_FORMAL_PROMOTION_FORBIDDEN
BLOCK_FACTORFORGE_MINER_OOS_HOLDOUT_USED_FOR_SELECTION
BLOCK_FACTORFORGE_MINER_DATA_DEPENDENCY_UNRESOLVED
BLOCK_FACTORFORGE_MINER_OUTPUT_OUTSIDE_WORKSPACE
```

## 12. 实现边界

Coder 必须遵守：

- 不改 `skills/factor-forge-ultimate/SKILL.md`；
- 不修改 Ultimate 研报直达 Step1-6 路由；
- 不启动 production research；
- 不启动 worker；
- 不跑 formal Step3B / Step4 / Step6；
- 不重写 Data API；
- 不用 `git add .`；
- 不把已有 Alpha101 dirty research state 混入提交；
- 只提交 Miner MVP 相关文件和测试。

## 13. Reviewer 重点

Reviewer 应重点检查：

1. Miner 是否复用已有 Data API / datamart / operator，而不是重造数据系统；
2. Miner 是否没有改 Ultimate；
3. 研报直达 Ultimate 路径是否保持；
4. cheap screen 是否被明确标为 exploratory；
5. candidate packet 是否有 lineage、经济先验、数学对象、falsification；
6. 缺数据时是否写 data gap，而不是 raw-minute full-window fallback；
7. 输出是否都在 miner workspace；
8. smoke 是否覆盖缺数据、正常候选、queue、Ultimate 未修改。

## 14. Forwardable Coder Brief

可以直接转给 coder：

```text
请实现 Factor Forge Miner MVP adapter。

边界：
- 不改 factor-forge-ultimate，保持研报/PDF/券商报告可以直接走 Ultimate Step1-6 正式研究。
- 不重写 Data API，不新建 production datamart，不启动 production research / worker / formal Step3B / Step4 / Step6。
- 复用现有 Data API、datamart catalog、Formula/operator、Step4/评价指标能力。
- 不用 git add .，不要混入 Alpha101 dirty research state。

实现：
1. miner_capability_inventory：只读盘点现有 dataset/datamart/operator/template 支持状态。
2. miner_template_registry：注册至少 10 个模板，覆盖价格路径、成交量分布、流动性/flow proxy、波动结构、value occupation、turnover/liquidity。
3. candidate packet generator：生成带 template lineage、经济先验、数学对象、expected metric signature、falsification 的 candidate packet。
4. cheap screen runner：在 /tmp fixture 上输出 RankIC、RankICIR、group spread、long/short endpoint、monotonicity、coverage、turnover estimate 和 decision。
5. research queue writer：只把 send_to_formal_research 候选写入 queue，且标注 cheap screen 只是 exploratory evidence。
6. data gap report：缺 dataset/datamart/operator 时写缺口报告或 data request，不做 raw-minute full-window fallback。
7. smoke：覆盖 inventory、template、candidate、needs_data、cheap screen、queue、Ultimate 未修改、输出不逃出 workspace。

验收：
- py_compile PASS
- run_factorforge_miner_mvp_smoke.py PASS
- git diff --check PASS
- git status 显示只包含 Miner MVP 相关文件；不得包含 Alpha101 状态文件。
```
