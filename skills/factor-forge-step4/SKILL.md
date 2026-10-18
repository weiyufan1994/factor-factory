---
name: factor-forge-step4
description: Execute reviewed factor implementations and selected evaluations, diagnose data or numerical issues, and deliver reproducible factor values, metrics and account results.
---

# Factor Forge Step4

Step4 executes the reviewed implementation on formal inputs and evaluates it.
Step3's bounded samples are executability evidence, not full-window factor values.
Use the study's pinned Ultimate entry and manifest-selected workspace.

## Execute the fixed study

1. Confirm the current code/helpers have distinct Step2 review and subsequent
   Step3 deterministic/parity tests. Resolve stale/missing review through
   [Ultimate's checkpoint](../factor-forge-ultimate/references/local-code-review.md).
2. Read the Step3 data contract, frozen window and evaluation settings.
   Consume existing Data API inputs or explicitly prepared, reviewed research
   derivatives, together with their field mappings and state resolutions.
   Keep units, calendar, price basis, information time and missing/zero semantics.
3. Run the factor class and standard frame validator. Inspect coverage, warmup,
   duplicates, ties, missingness and variation before/after material transforms.
   Legal NaNs and real zero are different; a finite output is not proof of
   preserved information.
4. Execute the declared analyses/account backend. Preserve independent signal
   cadence, label horizon and rebalance policy. A 20-day label does not determine
   monthly orders. Use the shared SDK and existing engine, not per-factor wrappers.
5. Write actual outputs and backend status. A failed or partial run remains so;
   missing metrics carry reasons rather than synthetic zeros.

Read [inputs](references/input-contract.md) and
[outputs/backend timing](references/output-contract.md) for execution.
For large/minute/state-dependent data also read
[batching and state](references/batching-and-state.md).
When the required estimator state is built by research from standard Data API
fields, read [research-derived inputs](references/research-derived-inputs.md).
Explicit Qlib use reads [backend details](references/backend-details.md);
Qlib interoperability alone is not native-account parity.
Formal OOS/certificate work additionally reads [formal proof](references/formal-proof.md);
it is not an ordinary IS prerequisite.

## Interpret execution quality

Separate IC/event/Fama–MacBeth diagnostics, gross conditional outcomes and
after-cost account results. The quick self-quant backend is signal-only; it does
not simulate cash, positions or blocked fills. All-skipped or unusable required
evidence cannot be passed on as a completed backtest.

Keep the existing long-only mandate and frozen policy/costs. Long-short and
decile curves are diagnostics, not executable short-account evidence. Retain
ties, actual sample sizes and missing-signal cash periods. A changed benchmark,
window or trading assumption is an explicit research choice, not silent repair.

If a suspected defect appears, preserve affected outputs and send Step2/3 the
failing function, expected/observed behavior, minimal case and affected time/state.
Step3 repairs, Step2 re-reviews, then tests and affected computation resume.
A code defect is not economic falsification; weak returns alone are not a bug.
Use the existing journal when a role is unavailable.

## Deliver

Follow [human reproducibility](../factor-forge-ultimate/references/human-reproducibility.md):
annotated executed code, factor head/tail/date slices, full standard values,
stable metric names/units/sample counts, plots and the commands producing them.
Account results include the actual cash/positions/cost path, not just a summary.
Use `acceptance_summary` for its declared run/root/status fields when present.

From the pinned checkout, after review and tests:

```sh
python3 scripts/run_factorforge_ultimate.py --local-is-only \
  --report-id <report_id> --factor-workspace <workspace> \
  --start-step 4 --end-step 4
```

Step5 consumes the exact run and evidence. Keep execution, semantic review,
economic interpretation and formal acceptance distinct.
