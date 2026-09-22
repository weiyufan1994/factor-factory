# Factor Forge Skill Feedback: Alpha019 Council Synthesis 后仍无法进入 Child Materialization

Date: 2026-05-19

Report id:

```text
ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811
```

## 结论

上一轮修复已经解决了一个关键问题：child materializer 不再从泛化 handoff 文本隐式兜底生成 `negate(parent_formula)`，并且要求主 agent 写 `main_agent_council_synthesis`。

但 fresh Alpha019 生产路径复测发现下一段链路仍然断开：

```text
completed real-agent Council
-> main-agent Council synthesis with selected child_formula
-> active approved Step3B handoff
-> materialize child executable_revision_spec
-> child Step3B/Step4
```

当前实际停在：

```text
completed real-agent Council
-> main-agent Council synthesis exists
-> wrapper rerun rebuilds dispatch_manifest and returns awaiting_agent_results
-> no active handoff_to_step3b
-> ultimate_loop cannot reach materializer
```

因此本轮不能正确声称 Alpha019 child revision 已跑完。正确状态应为 BLOCK / infrastructure gap。

## 已验证通过的部分

### 1. Fresh Step1 seed + official loop

Step1 seed 使用 canonical formula intake 只写 Step1 artifacts，Step2+ 通过 official loop/wrapper：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811 \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto \
  --auto-council-policy dispatch_manifest
```

首次暂停符合预期：

```text
final_outcome=awaiting_main_agent_mechanism_memo
```

### 2. Main agent mechanism memo

主 agent 写入：

```text
objects/research_iteration_master/main_agent_mechanism_memo__ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811.json
objects/research_iteration_master/main_agent_mechanism_memo__ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811.md
```

validator:

```bash
python3 skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811
```

Result:

```text
PASS
```

### 3. Real agentic Council

wrapper 进入：

```text
revision_council.status=awaiting_agent_results
effective_mode=agentic_dispatch_manifest
deterministic_scaffold_used=false
```

5 个真实 subagent result 均写入并通过 validator：

```text
objects/research_iteration_master/revision_council/ALPHA019.../agent_results/
```

Result validator:

```bash
python3 skills/factor-forge-step6/scripts/validate_agentic_council_result.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811
```

Result:

```text
PASS
```

Collection:

```text
valid_result_count=5
missing_result_count=0
ready_for_finalize=true
```

Finalize:

```bash
python3 skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811
```

Result:

```text
PASS
side_effects_unchanged=true
```

### 4. Main-agent Council synthesis

主 agent 写入：

```text
objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811/main_agent_council_synthesis__ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811.json
objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811/main_agent_council_synthesis__ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811.md
```

Selected law:

```text
alpha019_persistent_7d_boundary_single_trial
```

Selected child formula:

```text
multiply(
  negate(sign(sum(plus(minus(close, delay(close, 7)), delta(close, 7)), 3))),
  plus(1, rank(plus(1, sum(returns, 250))))
)
```

Formula parser:

```text
parse_status=success
child_formula_hash=eda12de7c7139024496b7054064b7e7fbdc004295f8407d22664c7139f40d2ba
required_fields=["close","returns"]
operator_set=["delay","delta","minus","multiply","negate","plus","rank","sign","sum"]
```

## 断点

Council finalize 后，Step6 attach 仍保持：

```text
final_revision_strategy.loop_authorization=advisory_only
handoff_to_step3b absent
```

并且 wrapper 在下一次：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_ORCH_SYNTH_RETEST_20260519_154811 \
  --start-step 6 \
  --max-loops 10 \
  --council-mode auto \
  --auto-council-policy dispatch_manifest
```

没有消费已有的 completed Council results 和 main-agent synthesis，而是重新构建 dispatch manifest，并再次返回：

```text
final_outcome=awaiting_agent_results
stop_reason=revision_council_awaiting_agent_results
handoff_to_step3b_exists=false
```

这导致 `materialize_step6_child_revision.py` 不可达。即使 synthesis 已存在，也没有 active approved `handoff_to_step3b__<report_id>.json` 给 ultimate loop 调用 materializer。

## Root Cause 判断

当前合同只补了：

```text
missing synthesis -> materializer BLOCK
synthesis exists -> materializer uses selected child_formula
```

但缺少一个中间状态机：

```text
Council finalized + main_agent_council_synthesis valid + human/default approval
-> activate approved Step3B handoff
-> final_revision_strategy.loop_authorization=approved_for_step3b_handoff
-> ultimate_loop can_continue
-> materializer writes executable_revision_spec
```

现在 `attach_revision_council_to_step6.py` 明确把 Council output 保持为 `advisory_only`，这符合旧安全规则，但没有后续 approved synthesis activation 脚本或 wrapper branch。

## 需要补的合同

建议新增一个明确脚本/阶段，例如：

```bash
python3 skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py \
  --report-id <parent_report_id> \
  --approval-source user_default_approval \
  --synthesis-path objects/research_iteration_master/revision_council/<rid>/main_agent_council_synthesis__<rid>.json
```

该脚本应：

1. validate synthesis contract/version/report_id/permissions。
2. validate selected law exists in finalized Council result or explain why it is a main-agent synthesis of multiple laws。
3. validate `selected_revision.child_formula` parses and formula hash differs from parent。
4. write/activate `handoff_to_step3b__<report_id>.json` from the archived provisional handoff or a new approved handoff schema。
5. set `orchestrator_synthesis_path` or `main_agent_council_synthesis_path` in handoff。
6. update Step6 iteration `final_revision_strategy.loop_authorization=approved_for_step3b_handoff` only after approval.
7. rerun `validate_step6.py` and require `handoff_to_step3b_exists_when_authorized`.
8. allow `run_factorforge_ultimate_loop.py` to proceed to child materialization.

## Acceptance Test

Use this Alpha019 fresh report or a `/tmp` fixture:

1. Step6 produces `awaiting_main_agent_mechanism_memo`.
2. Main agent writes memo; memo validator PASS.
3. Council dispatch enters `agentic_dispatch_manifest`.
4. Five real/mock-valid agent results collect/finalize PASS.
5. Main agent writes synthesis with explicit child formula.
6. Approval script activates handoff and sets approved loop authorization.
7. Ultimate loop materializes child.
8. Child executable spec references:
   - `source_orchestrator_synthesis_path`
   - selected `law_id`
   - selected `child_formula`
9. Child formula hash differs from parent.
10. Child Step3B reads child executable revision spec.
11. No generated code parent mutation, no clean data mutation, no search worker, no official promotion unless promotion gate later passes.

## Current Alpha019 Research Interpretation

Parent fresh metrics:

```text
rank_ic_mean=0.028308861729378878
rank_ic_ir=0.2774505165597732
pearson_ic_mean=0.024701021083208863
pearson_ic_ir=0.23639155458692057
long_side_annual_return=0.04299924220226802
turnover_mean=0.30446674745086055
cost_adjusted_annual_return=-0.18705878724380257
long_side_max_drawdown=-0.4882542593817618
```

Economic/math thesis remains only partially supported:

```text
slow winner state × short-horizon adverse shock
stochastic process: log P_i,t = X_i,t + M_i,t + U_i,t + epsilon_i,t
payoff claim: E[r_i,t+1 | F_t, high M_i,t, persistent negative U_i,t] > 0
```

But current parent is not promotable because cost-adjusted return, drawdown, and recovery fail. The selected child formula is the correct next falsification trial, but it has not been formally executed due to the approval-to-handoff bridge gap above.

