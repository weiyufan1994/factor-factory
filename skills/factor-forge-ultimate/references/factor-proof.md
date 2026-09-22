# Formal factor proof and OOS release

Read only when preparing, interpreting or verifying a formal certificate/OOS release/promotion. Local IS neither acquires this authority nor needs Host deployment. Read the named certificate contract for this mode; the commands below are not new authorization.

### 3. Factor Proof Certificate

All claim classes require IC, ICIR, volatility cost, transaction cost, maximum
drawdown and long-end return. Fama-MacBeth and quintile/decile monotonicity are
mandatory only for `claim_class=risk_premium`.

For non-risk-premium factors, bucket plots may diagnose shape but must not be a
universal acceptance gate. Long-short and short-leg results are diagnostic only.

Thresholds must be registered before evaluation. The verifier recomputes metric
identities and the final verdict. Every required metric must bind to its own
trusted-verifier report, exact metric payload, and the same dataset-snapshot
and window hashes. The locked rule set must bind factor/report/claim/window and
the frozen search-trial ledger, and contain at least one rule on a core decision
field for every required metric family. A formal
`promote_official` decision is blocked before official writeback unless this
certificate derives `ACCEPT`.

Before any realized metric is read, freeze a structured `evaluation_design`
that separately names: cross-sectional ordering metrics; absolute high-score
long NAV, return, Sharpe and drawdown; after-cost excess versus the same eligible
universe; portfolio weights, t+1 entry/t+2 exit, turnover and capacity; minimum
breadth and maximum exclusions; and every standalone, leave-one-out, sign and
alias diagnostic. Positive IC or gross long return never substitutes for the
after-cost long and relative-benchmark gates. A prose promise to run controls or
ablations is not executable evidence.

Use the formal release sequence. Do not inspect the OOS panel through
`--identity-only` before threshold registration:

```bash
python3 scripts/write_factorforge_evaluation_release_chain.py freeze-search ...
python3 scripts/write_factorforge_evaluation_release_chain.py register-threshold \
  --workspace-root <factor_workspace> \
  --spec <metric_verifier_spec.json> \
  --decision-rules <decision_rules.json>
python3 scripts/write_factorforge_evaluation_release_chain.py release-oos \
  --workspace-root <factor_workspace> \
  --panel <frozen_oos_panel> \
  --spec <metric_verifier_spec.json> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>

python3 scripts/build_factorforge_metric_verifier_reports.py \
  --workspace-root <factor_workspace> \
  --panel <frozen_oos_panel> \
  --spec <metric_verifier_spec.json> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>

python3 scripts/validate_factorforge_factor_proof.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

For a web-created task, its plan materializer performs the freeze-search and
threshold-registration stages before Step4. For a non-EVO or an EVO
`NO_QUALIFIED_CONTRADICTION` path, the formal wrapper runs
`scripts/finalize_factorforge_web_factor_proof.py` at the authorized release
point. For an EVO run still in `PREDICTIONS_FROZEN` or any qualified-revision
state, it must instead write/replay the purged-IS checkpoint and pause; calling
the OOS finalizer there is forbidden. The finalizer releases and replays the
exact plan-bound panel, writes the factor-proof certificate and bound verifier,
and fails closed on plan, calendar, label, risk-control, panel or hash drift.
Re-running an already finalized proof is permitted only as an identical
verified replay.

The release command binds actual OOS dates, at least 60 daily periods, panel
hash, locked rules and the frozen trial ledger. The full verifier must consume
that same panel and threshold file. The certificate validator replays the
panel/spec with the current verifier source. Do not hand-author passed metric
evidence. This is a tamper-evident local ordering contract, not an external
trusted timestamp; hard OOS secrecy requires an independently controlled data
release service.

Formal metric-verifier v2 accepts only a disjoint one-trading-day return path:
`forward_return_horizon_days=1`, `holding_period_days=1`,
`return_path_mode=daily_one_period_forward_return`, daily rebalance, and
`execution_timestamp=label_start_timestamp`. The atomic panel must also carry
signal date, label start/end dates, and label start/end prices. The verifier
must use the complete authoritative calendar independently resolved by
`factorforge_data_access.trade_cal_csv`; its actual file must be outside the
factor workspace. Its normalized open-date snapshot must match the repo-tracked
trusted calendar registry as read from its approved Git anchor commit/blob.
Formal specs must declare `verification_scope=production`, and the release/proof
chain must bind the raw file SHA, normalized snapshot SHA, registry SHA, anchor
commit/blob, and explicit snapshot id. A task or directory name containing
`SMOKE` cannot relax this scope. The verifier must
prove consecutive trading dates and daily signal coverage, and recompute
`label_end_price/label_start_price-1`; self-reporting horizon 1 is insufficient.
Multi-day rolling labels may
support IC/Fama-MacBeth/mechanism diagnostics, but must not be compounded as
daily long-end returns. Until a daily holding/NAV cohort engine or an explicit
non-overlapping stride contract exists, a `t+5` formal portfolio proof is
BLOCK. A locked threshold registration is immutable: identical retry is
idempotent, while different content at the same path is BLOCK.

Long-end admission uses geometrically compounded net return plus positive
terminal/minimum wealth. Arithmetic gross-minus-cost return is reconciliation,
not a substitute. Risk-premium quantiles are value based; unresolved ties that
collapse 5/10 buckets BLOCK rather than being split by asset order.

`component_validated` also requires deterministic full-versus-ablated evidence:

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

These four commands are Host-current formal entry points. Agent-side or
`--identity-only` replay is structural/diagnostic only, must expose
`current_formal_authority_verified=false`, and cannot establish formal proof
eligibility.

The sync tool must verify the latest manifest sha256 before applying a bundle. Protected records such as official library, factor cases, handoffs, and validation evidence must not be overwritten by default.

Full SOP: `docs/operations/factorforge-knowledge-sync-sop.zh-CN.md`.

## Factor Proof Policy

Read `docs/contracts/factorforge-factor-proof-certificate-v2.zh-CN.md`.

Common proof obligations:

- IC and ICIR, with conventions and arithmetic reconciliation;
- realized volatility drag and half-variance benchmark;
- gross-to-net transaction-cost reconciliation;
- maximum drawdown and recovery geometry;
- executable after-cost long-end return;
- metric-matching evidence file, exact metric-payload equality, verifier and
  SHA256 binding;
- one shared dataset-snapshot and window hash across required metrics;
- actual observed OOS dates and at least 60 daily periods;
- `verification_scope=production` plus an explicit calendar snapshot id bound
  to the approved trusted-registry Git commit/blob; `SMOKE` naming is never an
  authority;
- frozen search-trial ledger, locked threshold registration and one-time OOS
  release manifest in strict sequence;
- trusted metric-verifier identity and verifier-report contract;
- locked threshold-file hash bound to factor/report/claim/window and search
  ledger identity before the OOS panel is bound;
- one verdict rule on a core decision field per required metric family, and an
  automatically derived verdict.

Formal `promote_official` is blocked before official writeback unless the
certificate verdict is `ACCEPT`.

Build required evidence from the frozen OOS panel with
`scripts/build_factorforge_metric_verifier_reports.py`; its bundle is the
source of certificate metrics and evidence bindings. Researcher-written metric
JSON or Council prose is not a trusted verifier report.

Before that verifier, use
`scripts/write_factorforge_evaluation_release_chain.py` in this exact order:
`freeze-search`, `register-threshold`, `release-oos`. Formal threshold
registration must not use `--identity-only` to inspect the OOS panel. The
release command binds its actual dates, period count and dataset hash. This is a
local tamper-evident chain, not an external trusted timestamp.

For `measurement_validity` and `component_ablation`, freeze a same-window panel
containing full signal, ablated signal and legal forward return, register the
delta rules, and run:

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

Formal release, metric/component verifier, and factor-proof validation CLIs
must receive the same explicit Host `--host-trust-root` and
`--installation-id`. Agent-side/identity-only replay is structural diagnostic
evidence only and cannot set `formal_proof_eligible=true`.

Both metric and component evidence are replayed from their panel/spec by the
final kernel. A copied verifier ID, source hash, or hand-authored PASS file is
not proof.

Only `claim_class=risk_premium` requires Fama-MacBeth risk-price evidence and
quintile/decile monotonicity. Do not reject an event, threshold, liquidity-rent
or information-rent factor merely because all buckets are not monotonic.
Long-short spread and the short leg never substitute for long-end admission.
Formal long-end admission uses net geometric return and positive wealth, not
the arithmetic gross-minus-cost reconciliation. Ties may not be broken by asset
order to manufacture full quantile buckets.
