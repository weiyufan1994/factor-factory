# Step5 output and maintenance notes

All paths are relative to the declared workspace.

| Output | Path |
|---|---|
| Case | `objects/factor_case_master/factor_case_master__{report_id}.json` |
| Validation | `objects/validation/factor_evaluation__{report_id}.json` |
| Step6 handoff | `objects/handoff/handoff_to_step6__{report_id}.json` |
| Accepted archive | `archive/{report_id}/` |
| Prewrite failure | `objects/validation/step5_prewrite_block__{report_id}.json` |

`final_status` is `validated|partial|failed`. Keep actual archive paths, source
and evidence identities, implementation-mode decision and source references.
The Step4 quality result exists in evaluation and case; a blocking result forces
a failed case. The prewrite check precedes archive/handoff, so an identity or
evidence failure does not produce a validated-looking archive.

Preserve `research_window_contract`, `oos_revision_policy`, the measurement
program and existing legacy mathematical fields. `math_discipline_review`
records information-time status, spec stability, signal/account gap and overfit
risks. Missing values remain unknown; conflicting nonempty definitions fail.

## Existing information-set classification repair

The producer distinguishes forward formula/operators and negative shifts from
explanatory prose. A mention of future information in prose, even a prohibition,
needs actual independent confirmation; text alone proves neither leakage nor safety.

For an existing case affected by the old substring classifier, the scoped
`scripts/repair_step5_information_set.py` procedure preserves original bytes,
binds all inputs, changes only case/handoff metadata to unconfirmed and runs
the native validator under an explicit Step5 continuation. Keep maintenance
identity separate from the original writer. Step6 still needs actual timing and
mutation evidence; a metadata repair is not a corrected factor/backtest.
