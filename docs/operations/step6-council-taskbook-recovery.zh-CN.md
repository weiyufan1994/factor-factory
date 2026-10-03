# Step6 Council 任务书接续

适用于原生 `run_step6`、`validate_step6` 已成功，而 Council 任务书因
`BLOCK_AGENTIC_COUNCIL_DISPATCH_BLIND_CONTEXT_LEAK` 阻断的研究。
这是任务书生产与分发修复，不重新运行因子、回测或指标计算。

## 原研究保留什么

- 保留原失败 proof、已通过的 Step6 memo、Step2 规格和 measurement program。
- 保留研究 manifest 的原 repo、Python、SDK、catalog 和 trial 计数。
- 不修改冻结 release，不把已有研究迁移到新的默认版本。
- 工程修复只从经 review 的固定维护包调用；新 receipt 记录维护包 commit、
  调用脚本哈希、原 runtime/pin、原输入哈希、实际命令和退出状态。

先检查该报告尚无成功 dispatch、已有 agent 结果或签名 Council 输出。
已有有效 dispatch 应按既有流程继续消费，不覆盖任务或重派 agent。
若已有失败任务产物，研究 owner 先将它们原样归档并保留哈希与失败原因。

## 仅生成和校验 Council 任务

下列路径必须填为当前研究与已验收维护包的绝对路径；Python 仍选原研究绑定的环境。
`FACTORFORGE_LOCAL_IS_ONLY=1` 仅用于原本就在本地 IS 范围的研究，不得把 hosted
研究降级到本地范围。维护脚本用自己的固定源码，产物仍写入原研究 workspace。

```sh
ff_maintenance=/absolute/path/to/reviewed-maintenance-release/factor-factory
ff_study=/absolute/path/to/original-research-workspace
ff_python=/absolute/path/to/original-pinned-runtime/.venv/bin/python
ff_report=REPORT_ID

export FACTORFORGE_ROOT="$ff_study"
export FACTORFORGE_LOCAL_IS_ONLY=1
export PYTHONDONTWRITEBYTECODE=1

"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py" \
  --report-id "$ff_report" --executor dispatch_manifest \
  --runtime-dispatch codex --research-protocol required
"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py" \
  --report-id "$ff_report"
"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py" \
  --report-id "$ff_report"
```

任一步失败即停止后续分发，保留真实输出。旧 pin 的原生 dispatch validator 可再做
兼容消费验证。以上命令不调用 Step3–5，不生成假 agent 结果，也不代表 Council 已完成。

## 盲审的交付边界

盲审 agent 只读自己的最终 task packet 和其中声明的公开证据：精确公式、实现模式、
原样绑定的公开 measurement program、执行指标、图表及该 route 的研究任务。
不向其提供完整 Council packet、共享 taskbook、主研究员 memo、loop brief、主判断或
修订结论；不得继承已经看过这些内容的研究会话。被保留材料的评价应明确写为
`not_visible`，不得假装已经审阅。

非盲角色继续获得允许的主推导、判断、历史修订和 memo 引用，负责相应评议。
完整源材料的谱系保存在协调者的 taskbook/manifest；盲审任务没有指向它们的读取入口。
生成器与最终 dispatch validator 均检查结构化泄漏，不能通过给污染任务重算哈希绕过。
该检查约束结构化材料和引用，不宣称能识别任意自然语言中的隐含暗示。

所有独立 agent 必须真实执行并产生可验证身份与结果，随后按既有 collect/finalize、
Council 附加和 Step6 验证流程收口。任务书通过、离线回放通过、真实 Council 完成、
因子有效和生产晋升是不同结果，应分别报告。

## 已有真实结果明确不修订时的消费接续

普通非 EVO Council 可以有充分推导、反例与证据，但没有可辩护的新公式。
这类结果必须明确提供 `candidate_revision_laws: []`、无候选公式、
`no_revision` 或 `no_derived_revision` 建议及理由，范围限于
`revision_branch_only`，权限限于 `advisory_only` 或 `branch_falsification_only`。
其他身份、绑定、推导和证据要求仍完整适用；不能填写占位公式绕过旧校验。
EVO 的正式无新定律流程保持独立。

若旧 result validator 仅因空 law 列表阻断，保留原失败记录和已经成功的 dispatch，
由研究 owner 使用已 review 的固定维护源码消费原结果。不要重新生成任务书、覆盖
agent 结果或重派盲审。维护代码统一精确匹配冻结对象的 `name`、`object` 和
`mathematical_object` 字段；公开推导仍要求对象记录列表。

```sh
# 接续上文的 ff_maintenance、ff_study、ff_python、ff_report。
ff_original_repo=/absolute/path/to/original-pinned-runtime/factor-factory
ff_sdk=/absolute/path/to/original-pinned-runtime/factorforge-data-api
export PYTHONPATH="$ff_maintenance:$ff_sdk"

"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/validate_agentic_council_result.py" \
  --report-id "$ff_report"
"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/collect_agentic_council_results.py" \
  --report-id "$ff_report"
"$ff_python" "$ff_maintenance/skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py" \
  --report-id "$ff_report"
PYTHONPATH="$ff_original_repo:$ff_sdk" \
  "$ff_python" "$ff_original_repo/skills/factor-forge-step6/scripts/validate_step6.py" \
  --report-id "$ff_report"
```

任一步失败即停止，保留输出后定位，不以新签名或新终止证明消除工程报错。
验收应确认所有真实结果有效、law 与 branch 均为空、原 agent 结果和受保护产物哈希
未变、没有 Step3B handoff。若研究原本已有经作者及独立评议一致的本地拒绝，
消费者仅在既有严格识别规则通过且无修订动作时保留其状态，记录
`advisory_no_revision` 与 `not_needed`。一般无效或缺失结果仍为 blocked。
这不会授予终止整个因子或机制家族的权限，不改变研究 pin、trial 计数或正式晋升状态。
