# Step6 review and discovery prompts

Use the relevant section as a research aid. Do not regenerate the frozen
measurement program from this prompt or force a new mechanism/branch to finish
an output form. Existing artifact fields are summarized in
[current-operating-contract.md](current-operating-contract.md); formal landing
also obeys [compatibility constraints](../../factor-forge-ultimate/references/compatibility-constraints.md).

## Evidence and research-equation review

What did the study actually measure? Which preregistered predictions survived,
which failed, and which cannot be assessed? Relate evidence to the selected
mathematical object, assumptions, market-outcome projection, applicable audits,
observation map, implementation and costs. Do not insist that every metric
uniquely identifies a failed layer or an economic cause.

Useful comparisons, where evidence exists:

- Rank IC tests ordering versus the declared payoff/sign; it does not by itself
  establish the latent object, mechanism or payer.
- Long-side gross and net/relative return assess the implemented economic claim;
  positive gross return alone does not confirm its explanation.
- Turnover and explicit costs assess implementation economics and participant
  horizons. Volatility drag is a log-growth/compounding diagnostic.
- Drawdown, recovery time/area, capacity and regime evidence describe stress and
  capital use; they do not prove a particular risk mechanism without tests.

Land `research_equation_review` with `equation_status`,
`equation_supported_by_metrics=supported|challenged|under_specified`, metric links,
the supported failed component and `revision_implication`. Keep unavailable
metrics and unidentified components explicit in the memo; do not invent a cause
to fill a field. Preserve the exact upstream measurement program and its
formula-specific public derivation; add stochastic or dimensional fields only
when that mechanism uses them.

Investigate unexpected implications rather than silently removing them. In
`dirac_anomaly_review`, distinguish bug/data/implementation evidence, benign
model implications, research candidates and rejection only as supported. If
unresolved, keep that uncertainty in the evidence/memo and do not force an enum
or claim a confirmed defect. Current schema limitations may block formal landing.
`approved_for_branch_generation` stays false without the applicable approval.
`new_factor_seed`/`tradable_anomaly` entries require their actual candidate
binding, expected signature and kill criteria; an empty candidate queue is valid
when the active consumer allows it.

## Bounded revision or stopping

Is the problem an implementation mismatch, unavailable measurement, an economic
counterexample or non-identification? Repair lower layers before inferring a new
law. If no justified revision exists, reject, stop, or preserve the unresolved
question. A non-obvious revision may need Council; a routine defect returns to
Step2/3 and the code-review/test sequence.

For a proposed revision, name the changed mathematical term and mechanism,
preserved invariants, new prediction, distinguishing test, added complexity,
trial boundary and kill criterion. Preserve direct-code/hybrid mode unless an
operator conversion is explicitly proved with parity. Large input/training
methods need a bounded batch plan. Do not change portfolio mechanics or tune
parameters on observed return to make adoption pass.

## Optional discovery

When new ideas are requested or the evidence motivates an explicit exploratory
question, allow associations among economics, mathematical objects, observations,
constraints, symmetries and counterexamples. Equation search can help; it is not
the only allowed starting point. Do not force every relation into a symmetry-
breaking story or the existing library's methods.

Before a candidate becomes an evaluated claim, make its economic hypothesis,
object/estimand, source versus inference, legal observable inputs, measurement
map, predicted signature, costs/risks and falsifiers explicit. An equation-derived
candidate retains `source_equation_id`, `equation_status`, `evidence_tier`,
`measurement_equation`, `market_outcome_projection_terms`, `required_controls`,
`expected_metric_signature`, `expected_cost_risk_profile`, applicable audits,
`falsification_tests` and `kill_criteria`. Unknowns can remain research questions.
Use `branch_action=review_only|human_approval_required` and
`auto_run_allowed=false`; this prompt never launches Step2/3/4 or grants child
execution authority. No candidates is an honest result.
