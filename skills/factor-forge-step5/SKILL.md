---
name: factor-forge-step5
description: Check and organize factor evaluation evidence, preserve results and limitations, and hand off a reproducible case for research judgment and learning.
---

# Factor Forge Step5

Step5 checks actual Step4 evidence and records the case. Step6 owns the economic
judgment and revision. Execute through the study's pinned Ultimate entry.

## Check and preserve

- Consume the manifest-selected run, spec, data preparation and handoff.
  Validate identity, required backend artifacts, finite/consistent metrics and
  factor-value quality before claiming a usable case.
- Preserve the upstream measurement program, research window and existing math
  metadata exactly. Conflicting definitions are errors; missing information
  stays missing. Mathematical explanation does not substitute for execution.
- Separate signal/event diagnostics from account evidence, and valid observations
  from incomplete or bug-affected outputs. Quality status is not a profit verdict.
- Record the evidence that can be reused, its limits and Step6's next questions.
  Genuine failure or no new lesson is more useful than invented learning.

Read [inputs](references/input-contract.md) and [outputs](references/output-contract.md)
when writing the case. The implementation is `factor_factory.step5`; historical
module names forward to that same library.

Verify the [human-reproducible handoff](../factor-forge-ultimate/references/human-reproducibility.md):
annotated executed class/helpers, command, full standard values and sample slices,
the same standardized metrics, and relevant plots. Preserve units, sample counts,
timing and unavailable reasons. A statistics-only result is not an account test.

## Return real defects to their owners

A blocking Step4 quality result makes the case failed and preserves the concrete
finding. Return suspected code/spec/data defects through Ultimate to Step4 and
Step2/3; re-review and retest repairs before recomputing affected results.

Illegal information time blocks use. An unconfirmed timing classification is
a warning to resolve with actual code/PIT evidence, not proof of leakage or safety.
For existing cases affected by the old prose-substring classifier, use the scoped
maintenance procedure in [output notes](references/output-contract.md), not a new
interpretation of historical research.

## Close and hand off

```sh
python3 scripts/run_factorforge_ultimate.py --local-is-only \
  --report-id <report_id> --factor-workspace <workspace> \
  --start-step 5 --end-step 5
```

Case status is `validated|partial|failed`; validation is `PASS|WARN|BLOCK`.
Archive and handoff follow the existing prewrite checks. An identity/evidence
failure can produce a failed case and block record, not a validated-looking
archive. Continue Step6 with the exact evidence and its remaining limits.
Local experience is a maintenance candidate, not automatic canonical publication.
