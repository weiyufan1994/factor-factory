---
name: factor-forge-step2
description: Formalize a Factor Forge source or hypothesis into a canonical mathematical and measurement specification, reconcile independent readings, and review Step3 code against that specification before Step4.
---

# Factor Forge Step2

Step2 owns source fidelity and the mathematical specification. It consumes
Step1's `alpha_idea_master` and actual source/hypothesis; emits
`factor_spec_master`, independent raw specs, the consistency review and
`handoff_to_step3`; later it reviews Step3's code. That later review is not a
circular prerequisite for the initial spec handoff. Execute through Ultimate.

## Preserve the research object

For `report_replication`, recover the author construction, including components,
sign, windows, grouping/aggregation order, normalization and weights. Explain and
challenge that estimator before proposing another. Separate source statements,
reconstruction assumptions and new ideas. `source_extension` is a separately
identified estimator; `independent_hypothesis` needs no paper baseline. A high
consistency score or valid JSON cannot establish source fidelity.

Keep economic hypotheses, mathematical mechanisms, alternative explanations and
unknowns visible. Open tool search permits new objects/methods absent from the
knowledge base. Choose the smallest appropriate tool set, without forcing
stochastic processes, dimensional analysis, valuation or latent states. Use
free exploration to discover questions; freeze estimand, observation/estimation
map, information timing, component semantics and distinguishing predictions
before evaluation. The formal artifact is a record of those decisions, not a
required sequence for thinking or a quota of ideas.

Preserve Step1's economic/math hypotheses and knowledge provenance. Retrieved
cases are priors, counterexamples or tools, not source evidence or current-factor
proof. Cold-start is valid with honest retrieval provenance. No data convenience,
operator availability or payoff result may silently change the selected object.

## Decide and formalize

Use genuinely independent primary and challenger extractions, with the same
source/upstream inputs and separate contexts. Save each before showing the
other's answers. The same capable model may serve both; copied output, model
labels or failed calls do not establish independence. Choose capability and
reasoning effort for difficulty/cost, not a fixed provider or `max` default.

Compare both readings against the original source and the actual selected
construction. Any material disagreement—including one sign or timing error—needs
source-based chief adjudication. Preserve alternatives, evidence, reasoning and
original route outputs; do not overwrite them to create agreement. When no
material disagreement exists, still justify canonical selection against the
source. A score never selects the primary automatically.

A nonmaterial numerical convention may be selected before results as an explicit
reconstruction assumption, with sensitivity checks where needed. Escalate only
an unresolved choice that materially changes the estimand and lacks a defensible
source basis. Unknown economics limits the claim; it does not authorize changing
the source formula. Formal completeness constraints still apply: mark an honest
`under_specified`/blocked record if unsupported, never fabricate a mechanism to pass.

Bind every material component to its mathematical term, input/output measurement
semantics, legal information time, implementation, retained/deleted information,
expected signature, ablation and falsifier. `operator`, `direct_code` and `hybrid`
are equally valid when justified by the mathematical/numerical method. Return
unavailable measurements for an explicit proxy-error contract, data request or
BLOCK; do not replace the estimand. Legacy math contracts are preserved only
when already present upstream, never generated for a new study.

## Read at the relevant boundary

| Task | Required reference |
|---|---|
| New/finalized mathematical specification | [Measurement program](../../docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md) |
| Write Step2 objects | [Schema and current fields](references/schema.md); [source/producer contract](../../docs/contracts/step2-contract.md) |
| Local PDF input landing | [Local PDF inputs](references/local-pdf-inputs.md) |
| Bind operator or hybrid implementation | Selected section of [implementation contracts](references/implementation-contracts.md) |
| Author state/conjecture/approaches | [Ultimate research protocol](../factor-forge-ultimate/references/research-protocol.md) |
| Interpret fixed fields/counts or a validator conflict | [Compatibility constraints](../factor-forge-ultimate/references/compatibility-constraints.md) |
| Review code before local Step4 | [Local code review](../factor-forge-ultimate/references/local-code-review.md) |

[Prompts](references/prompts.md) are optional question/record aids, not a second
mandatory manual. [Architecture](references/architecture.md) explains input and
producer routing when debugging. Read legacy contract docs only for artifacts
that actually carry them.

## Review Step3 implementation

The reviewer must be distinct from the code author. Read the source, frozen
spec/measurement program, actual implementation and invoked helpers, numerical
assumptions and proposed tests together. Trace each mathematical term to code
and observable output. Where applicable check sign/units, lag/window/order,
ties, missing versus zero, information and label timing, initialization,
readiness, recursive state, resets/chunks and approximation error. Derive needed
warmup/recovery behavior for recursive models; do not impose state on other models.
Tests need a spec-based or independently derived oracle, not duplicated code.

Record concrete findings and `proceed/revise` for the reviewed revision in the
existing journal/handoff. Step3 fixes, Step2 re-reviews, then Step3 runs
acceptance/parity tests, then Step4. Self-review, generator checks, bounded bug
probes and passing tests cannot replace researcher judgment. Behavior-changing
spec/code/helper edits invalidate affected approval and require fresh tests.

On Step4/5 feedback, distinguish implementation, specification, data and actual
empirical results. Review repairs promptly; a changed estimand/hypothesis or
post-result parameter choice is a research revision. Preserve observed outcomes
and the old baseline. Weak returns alone do not justify a repair.

## Handoff and completion

The source-contract validator checks the exact identity, route and required
objects; artifact paths come from the active workspace manifest. Formal outputs
must carry `artifact_identity`, producer/source type, mode, `spec_hash` and the
research/measurement context into Step3. A missing PDF on a PDF route fails
explicitly; non-PDF hypotheses do not require one. Local PDF specs must come
from real agent-authored inputs, never a generic correlation template.

A completed spec is implementable without silently guessing semantics, with no
unresolved material source disagreement. Code approval later certifies alignment
with that spec, not economic validity. Record actual agents/models and chief
adjudication in the journal or `source_semantic_review`; preserve the existing
`chief_decision` and `opus_invoked` compatibility semantics.
