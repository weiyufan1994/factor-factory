# Frozen raw minute inputs for engineering comparisons

Use the reviewed study pin with `run-ultimate --local-is-only --raw-local-inputs
declaration.json --start-step 3 --end-step 5` and the study's normal identity and
manifest arguments. This route cannot be combined with `--prepared-local-inputs`,
skip Step3A, replace EVO data evidence or fetch a missing file. It does not change
the factor, evaluation plan, output validators or review requirements.

The declaration contains exactly these three initial fields:

```json
{
  "input_mode": "raw_local_snapshot",
  "snapshot_manifest_path": "/absolute/path/snapshot.json",
  "snapshot_manifest_sha256": "actual SHA256 of snapshot.json"
}
```

The frozen manifest uses `schema: factorforge_raw_local_snapshot_v1` and
`scope: bounded_local_is_engineering`. It declares:

- `symbols` and `calendar_dates`: sorted, nonempty, unique string lists. Dates
  use YYYYMMDD. Both daily and minute data must cover exactly their product.
  This coverage requirement does not establish a legal investment universe.
- `daily` and `minute`: each an object with an absolute existing `path` and
  `sha256`. Daily requires ts_code, trade_date, close; minute additionally
  requires trade_time and vol. Other factor/evaluator requirements still apply.
- `source_identity`: catalog_sha256, daily_dataset_version,
  minute_dataset_version and daily_price_basis, preserving the actual release
  and price semantics. Additional provenance may be recorded in this object.
- `signal_timing: after_close_next_session`. Minute timestamps must parse, agree
  with trade_date and be no later than 15:00:00. Daily keys and normalized minute
  observation keys must be unique. No source clock/date fallback is permitted.
- `step3b_sample`: separate daily/minute file objects, subset symbols/dates and
  an explicit budget with positive integer max_symbols, max_calendar_days and
  max_minute_rows. The files must equal the corresponding exact full-data slice.
  Choose a bounded sample suitable for the factor's warmup; this is executable
  evidence, not the formal run. Full and sample file paths must differ.
- Optional `evaluation_plan`: the existing evaluator-plan schema. Use identical
  settings for the comparison arms; a new input route grants no metric changes.

Step3A validates the manifest and both slices, requires the full date bounds to
equal the declared research window, then generates its usual objects. Step3B
rechecks and reads only its sample files, preserving the full selection in its
handoff. Step4 rechecks the complete snapshot before consuming its existing raw
daily/minute path. File mutation, missing files, scope drift and attempts to mix
API or derived-state selectors fail without a fetch. Keep the manifest and
declaration immutable; do not patch generated DPM/handoff objects to inject data.

This is a local engineering input route. It is not a provider publication,
native Qlib account certificate, OOS grant, or architecture release decision.
