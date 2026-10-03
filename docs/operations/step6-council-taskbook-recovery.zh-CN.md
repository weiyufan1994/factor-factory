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
