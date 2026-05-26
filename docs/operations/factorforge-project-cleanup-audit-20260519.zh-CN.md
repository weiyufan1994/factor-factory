# Factor Forge Project Cleanup Audit - 2026-05-19

## 当前仓库状态

- Repo: `/Users/humphrey/projects/factor-factory`
- 当前分支: `codex/factorresearcher`
- 基线提交: `b72446c Update Factor Forge production skill and performance tracks`
- Remote: `git@github.com:weiyufan1994/factor-factory.git`
- 当前不是 linked worktree；本轮直接整理当前脏工作树。

## 已执行的无风险清理

- 删除所有未跟踪 `.DS_Store`。
- 删除所有未跟踪 `__pycache__/` 与 `*.pyc`。
- `.gitignore` 已覆盖上述缓存和 runtime/canonical 产物路径，不需要新增 ignore 规则。

## Dirty Files 分组

### A. Phase O/O2 机制数学与主 agent memo 合同

建议作为第一个独立提交/PR。原因：这是当前生产可用性的核心语义变更，且已有最完整验证。

文件：

- `factor_factory/mechanism_math/classifier.py`
- `factor_factory/mechanism_math/formula_specific.py`
- `factor_factory/mechanism_math/main_agent_memo.py`
- `scripts/run_mechanism_math_contract_smoke.py`
- `scripts/run_step12_from_report.py`
- `scripts/run_step12_hypothesis_contract_smoke.py`
- `scripts/deprecated/run_step1_sample.py`
- `scripts/step12_intake_common.py`
- `skills/factor-forge-step2/SKILL.md`
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor_forge_step1/modules/report_ingestion/research_discipline.py`
- `scripts/run_main_agent_mechanism_memo_smoke.py`
- `skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py`
- `docs/operations/factorforge-skill-feedback-alpha018-022-mechanism-agentic-council.zh-CN.md`
- `docs/operations/factorforge-skill-feedback-main-agent-mechanism-contract.zh-CN.md`
- `docs/operations/phase-o-*.zh-CN.md`
- `docs/operations/phase-o2-*.zh-CN.md`

Required verification before commit:

```bash
python3 -m py_compile factor_factory/mechanism_math/*.py scripts/run_main_agent_mechanism_memo_smoke.py scripts/run_mechanism_math_contract_smoke.py scripts/run_step12_hypothesis_contract_smoke.py
python3 scripts/run_main_agent_mechanism_memo_smoke.py --fresh --root /tmp/factorforge_main_agent_memo_release_check
python3 scripts/run_mechanism_math_contract_smoke.py --fresh --root /tmp/factorforge_mechanism_math_release_check
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_release_check
```

### B. Step6 / Ultimate current-agent memo pause and Council dispatch contract

建议作为第二个独立提交/PR，依赖 A。

文件：

- `factor_factory/ultimate_loop/state.py`
- `scripts/run_factorforge_ultimate.py`
- `scripts/run_factorforge_ultimate_loop.py`
- `scripts/run_factorforge_ultimate_loop_smoke.py`
- `scripts/run_step6_council_primary_smoke.py`
- `scripts/run_step6_intelligence_smoke.py`
- `skills/factor-forge-step6/SKILL.md`
- `skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py`
- `skills/factor-forge-step6/scripts/build_revision_council_packet.py`
- `skills/factor-forge-step6/scripts/build_step6_revision_proposal.py`
- `skills/factor-forge-step6/scripts/run_step6.py`
- `skills/factor-forge-step6/scripts/validate_step6.py`
- `skills/factor-forge-ultimate/SKILL.md`

Required verification before commit:

```bash
python3 -m py_compile scripts/run_factorforge_ultimate.py scripts/run_factorforge_ultimate_loop.py scripts/run_factorforge_ultimate_loop_smoke.py skills/factor-forge-step6/scripts/run_step6.py skills/factor-forge-step6/scripts/validate_step6.py
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_release_check
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_release_check
python3 scripts/run_agentic_council_dispatch_smoke.py --fresh --root /tmp/factorforge_agentic_dispatch_release_check
python3 scripts/run_step6_council_primary_smoke.py --fresh --root /tmp/factorforge_council_primary_release_check
```

### C. Step3/Step4 performance, data IO, and daily update entrypoint

建议作为第三个独立提交/PR。原因：这组是工程性能/数据路径，不应和机制语义混合审查。

文件：

- `factor_factory/data_access/qlib.py`
- `factor_factory/data_access/step4.py`
- `scripts/run_factorforge_performance_smoke.py`
- `scripts/step4_custom_backend_template.py`
- `scripts/update_clean_daily_bar_after_daily_update.py`
- `skills/factor-forge-step3/SKILL.md`
- `skills/factor-forge-step3/scripts/run_step3.py`
- `skills/factor-forge-step4/scripts/qlib_native_report_note.md`

Required verification before commit:

```bash
python3 -m py_compile factor_factory/data_access/*.py scripts/run_factorforge_performance_smoke.py scripts/update_clean_daily_bar_after_daily_update.py skills/factor-forge-step3/scripts/run_step3.py
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_release_check
```

### D. Factor family / topic-liquidity experimental work

建议作为第四个独立提交/PR，或暂时搁置。原因：它包含 family plugin 重构、`cpv.py` 删除、topic liquidity 报告脚本大改，风险和 Step1-6 主合同不同。

文件：

- `factor_factory/factor_families/base.py`
- `factor_factory/factor_families/cpv.py` 删除
- `factor_factory/factor_families/price_volume.py`
- `factor_factory/factor_families/registry.py`
- `factor_factory/factor_families/shadow_candlestick.py`
- `scripts/report_topic_liquidity_dragon_candidates.py`
- `scripts/topic_liquidity_hhi.py`

Required verification before commit:

```bash
python3 -m py_compile factor_factory/factor_families/*.py scripts/report_topic_liquidity_dragon_candidates.py scripts/topic_liquidity_hhi.py
rg -n "cpv|price_volume|shadow_candlestick" factor_factory scripts skills tests
```

## 不建议直接做的动作

- 不建议把所有 dirty files 做成一个提交。审查面过大，任何一个回归都会阻塞全部工作。
- 不建议直接删除 runtime canonical artifacts；`objects/`, `runs/`, `evaluations/`, `generated_code/`, `data/clean/` 已由 `.gitignore` 管理，清理应通过专门 archive/retention 策略，不应在本轮混入代码提交。
- 不建议回滚 `cpv.py` 删除或 topic-liquidity 改动，除非先确认这组实验是否继续保留。

## 推荐版本控制路径

1. 保持当前分支 `codex/factorresearcher` 作为集成工作分支。
2. 从当前脏工作树按 pathspec 分批 staging。
3. 先提交 A，再提交 B，再提交 C。
4. D 单独判断：如果 topic-liquidity/factor-family 是正式方向，则单独提交；否则另开分支保留或暂不提交。
5. 每个提交都要带对应 smoke summary 路径和命令，不用聊天记录作为证明。

## 当前最高优先级

先提交 A+B。它们决定 Factor Forge Ultimate 是否能按 current-agent mechanism memo 合同生产使用。
