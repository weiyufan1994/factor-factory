# Authored local hypothesis input

Use this route for a user's hypothesis or a separately identified extension in
`--local-is-only` research. It consumes real authored input and requires no PDF.
Keep the original argument and source-only interpretation in the workspace
before consulting prior cases. Primary and challenger reason in distinct
contexts; the chief resolves material differences against that argument.

## Land inputs, then let Step2 produce outputs

1. Save the two authored raw specs in separate workspace files, for example
   `inputs/primary.json` and `inputs/challenger.json`. Use the
   [raw-spec fields](schema.md#factor_spec_raw), plus
   `source_type=natural_language_hypothesis` and
   `producer=step12_hypothesis_intake`. These are format/route identifiers, not
   evidence that an independent agent ran.
2. Save the source understanding and adjudicated alpha idea at
   `objects/alpha_idea_master/alpha_idea_master__<report_id>.json`.
   Its report/factor identity, source type and producer match the raw specs.
   Use `research_subject_mode=independent_hypothesis` with no invented report
   reference; a genuine source extension uses the reference described in
   [source-subject inputs](schema.md#current-step2-source-subject-inputs).
3. On that alpha idea, set `local_agent_spec_inputs` with exactly
   `primary`, `challenger` and `chief_canonical_core`. Each route reference
   has a workspace-relative `relative_path`, lowercase raw-file `sha256`,
   `role=local_agent_primary_spec|local_agent_challenger_spec`, and
   `identity` containing `report_id`, `factor_id`, `route`,
   `source_type` and `producer`.
4. The chief's canonical core contains exactly `raw_formula_text`,
   `operators`, `required_inputs`, `rebalance_frequency`,
   `time_series_steps`, `cross_sectional_steps`, `preprocessing`,
   `normalization` and `neutralization`. Both finalized routes must match
   these decisions. Preserve their original independent readings, disagreements
   and the adjudication separately; equality is not evidence of independence.
   Empty operator/normalization/neutralization arrays are valid when appropriate.
5. Carry the actual `research_discipline`, measurement program, explicit
   `evaluation_contract`, and selected implementation input on the alpha idea.
   Use the existing [measurement fields](../../../docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md)
   and [implementation input](implementation-contracts.md), not a generic
   economics template. The ordinary content profile can express a justified
   absence of prior lessons or new ideas.

From the selected source checkout or unpacked package, run:

```sh
python3 scripts/run_factorforge_ultimate.py --local-is-only \
  --report-id <report_id> --factor-workspace <workspace_root> \
  --start-step 2 --end-step 2
```

Step2 loads these inputs and produces the master and handoff. This is not
permission to handwrite a passed master, review or research result. Afterwards
continue through the ordinary Ultimate sequence, including actual code review.

## Older scaffold command

`scripts/run_step12_from_hypothesis.py` creates a generic draft with guessed
variables, `hypothesis_score(...)` and `human_review_required=true`.
It does not perform the independent interpretation or mathematical derivation.
For a fully authored study use the explicit route above; do not relabel its
automatically generated primary/challenger drafts as independent readings.
An incomplete hypothesis remains incomplete until the researcher resolves it.

The maintained consumer is `run_step2.py:load_local_agent_dual_route_specs`;
`tests/test_step2_local_authored_hypothesis.py` checks transport and rejection
behavior using synthetic inputs, not an example of accepted research.
