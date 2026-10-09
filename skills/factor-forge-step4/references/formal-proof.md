# Formal certificate and held-out evidence

Read only for explicit formal certificate/OOS work. Ordinary local IS does not
run these release/finalizer operations. The active study's frozen contract and
Ultimate mode determine whether the action is authorized.

For a final factor-proof certificate, preregister through
`scripts/write_factorforge_evaluation_release_chain.py` before releasing a
workspace-local OOS panel with date, asset, signal, legal forward return and
risk controls. Actual dates and at least 60 daily periods are checked at
release. Then run `scripts/build_factorforge_metric_verifier_reports.py`. This deterministic
verifier, not Step4 narrative output, supplies the hash-bound IC/ICIR,
long-only cost/risk/return and claim-specific risk-premium evidence used by the
promotion kernel. When Step6 may claim component validation, Step4 must also
materialize a same-window full-versus-ablated panel with legal forward return
for `scripts/build_factorforge_component_obligation_report.py`; an ablation
summary written in prose is diagnostic only.

For a web-created research task, the materializer must write the immutable
search-trial ledger, metric spec and threshold registration before Step4 starts.
Step4 must carry the plan-bound OOS signal dates, label start/end dates,
label start/end prices, and required risk controls into the workspace-local
proof panel. After Step4, run
`scripts/finalize_factorforge_web_factor_proof.py`; it must replay the frozen
panel and write both the certificate and bound verifier. Missing or changed
dates, controls, plan hash, panel hash or release-order evidence must BLOCK.

Metric-verifier v2 formal portfolio evidence is limited to a disjoint one-day
return path. Step4 must declare horizon days, label start/end, execution time,
holding period and return-path mode, and materialize signal date, label
start/end date, and label start/end price columns. The kernel must verify
consecutive trading dates and daily signal coverage against the complete
`factorforge_data_access.trade_cal_csv` authority independently resolved
outside the factor workspace. Formal specs must declare
`verification_scope=production`. The normalized open-date snapshot must match
an explicit snapshot id in the Git-anchored trusted calendar registry; bind the
raw file SHA, normalized snapshot SHA, registry SHA, anchor commit/blob, and
snapshot id, then recompute
`label_end_price/label_start_price-1`. If execution is `t+1`, the label must
start at `t+1`; renaming a multi-day return column or supplying an unregistered
sparse calendar does not satisfy the gate. A security suspended on either
registered label date has no valid price path for that signal row; do not shift
to the security's next observed bar, and exclude the incomplete row from formal
evidence. Report or directory names containing
`SMOKE` never grant a different verification scope.
A rolling five-day forward label may be used for IC,
Fama-MacBeth or bucket diagnostics, but Step4 must not feed it into daily
geometric NAV, turnover, volatility or drawdown. Multi-day formal portfolio
evidence is BLOCK until a supported daily cohort/NAV engine or non-overlapping
stride contract is present. Threshold registration is write-once except for
an identical idempotent retry.
