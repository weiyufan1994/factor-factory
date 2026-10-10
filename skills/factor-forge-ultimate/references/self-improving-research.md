# Self-improving research loop

Read this reference when a research episode introduces a new response structure,
uses a hybrid-research proposal, or turns Step4/5 evidence into the next research
action. It is a research discipline, not an execution or release permission.

## Required induction for a new response structure

Before a new structure enters formal efficacy evaluation, the responsible
researcher records a concise, public-facing induction in the existing Step2
record and Step6 journal/handoff:

1. State the economic assumption and exactly what changed from the parent.
2. Define the mathematical object, information time, domain and symbols.
3. Derive forward implications under those assumptions. Let the derivation reveal
   useful states, predictions, counterexamples or identification limits; do not
   begin with a desired alpha and reverse-engineer a story.
4. Map the object to observations, estimators and code, naming proxies, retained
   and lost information, numerical conventions and legal timing.
5. Fix a discriminating test or falsifier, then state what follows, remains
   unknown, or is inconsistent.

An SDE is useful when the question is stochastic-process based, but is not a
universal template. A derived property, contradiction, non-identification or
inability to infer a return direction is a valid outcome. Completing an
induction and establishing that the candidate is consistent are separate facts.

## Candidate changes and action advice

Classify each candidate before code or evaluation:

- **Implementation equivalent:** preserve object, domain, initial state, clock,
  missing-value semantics and numerical behavior; establish parity with an
  independent oracle.
- **Measurement or estimation variant:** state changed information, bias/error,
  applicability and the revised observation map; return it to Step2 review.
- **New mechanism or response structure:** perform the induction above and
  return to Step2 before formal evaluation.

`factor_factory.hybrid_research.decision` may summarize comparable development
evidence and recommend a registered action. This recommendation does not execute
actions, create a mechanism, validate semantics, write canonical knowledge, or
replace Step2 code review. Its normalized delta is local to the stated metric and protocol, not an
information-gain, causal, trading-utility or alpha score. Final/confirmation
evidence never updates the current policy.

Record Step6's evidence-based decision as retain, revise, reject, unresolved or
stop with the next discriminating question where applicable. A failure,
unaffordable action, missing evidence or STOP is legitimate; preserve cost and
the evidence boundary. Suspected implementation defects still return to Step2
and Step3 for a distinct code review and regression test.

## Optional derivation audit

Use the [repository candidate Math Derivation Tutor](../../math-derivation-tutor/SKILL.md)
when a derivation,
observation bridge, numerical approximation or failed prediction needs a focused
audit. The responsible researcher still owns the induction. The Tutor is neither
a formal proof system nor an independent reviewer and is not a required extra
model call for ordinary work. This is a local audit adaptation for D0.4, not a
claim to have migrated or reproduced a separate Tutor system.

## Two search levels (D0.5 construction)

Use one research loop with two distinct search spaces:

- **Mechanism/research search:** explore economic assumptions, mathematical
  objects, response structures and discriminating experiments; exploit the
  current mechanism through estimation, counterexamples or targeted checks.
- **Expression search:** generate and mutate actual operator trees within a
  derived family, including legal crossover and tree expansion. Selecting an
  existing candidate list is not the same as generating formulas.

A new response structure requires the forward induction above before efficacy
evaluation. In-family parameter changes may reuse a derivation with a scope
check; matching units or an operator allowlist alone does not establish that
scope. Data-inspired proposals keep that exposure history after re-derivation.

Keep the layers' conclusions separate: a poor expression does not by itself
refute its economic mechanism, and a high score cannot repair inconsistent
mathematics. Use comparable evidence and cost to select the next experiment;
unknown rewards stay unknown. Derivation, identification, prediction and
trading performance answer different questions.

Generated expressions use the existing Factor class, Formula engine and standard
Step3/4/5 inputs, outputs and metrics. New search code does not replace those
interfaces or the distinct Step2 review of Step3 code. The implementation and
acceptance plan is [D0.5 construction](../../../docs/design/self-improvement-d05/02_construction.zh-CN.md);
see its adjacent status file before claiming the new engines are available.
The interfaces below describe the narrower existing implementations.

## Shipped interfaces and limits

Ordinary Ultimate execution leaves hybrid research off. Use an explicitly
accepted release's launcher and the study's existing pin. For a separately
authorized, bounded development fit against existing Step2/Step6 artifacts:

```sh
<release>/run-ultimate --report-id <report_id> --factor-workspace <workspace> \
  --hybrid-research-adapter-only --hybrid-research-request <request.json>
```

`--factorforge-root <workspace>` is also supported for an existing object root;
if both root and workspace are specified they must identify the same directory.
An old study pin is rejected. Adapter-only does not run Step3–6 or emit a formal
Ultimate proof. Normal Step3–6 retains the existing review and execution route.

The request contract is `hybrid_research_request_v1`, parsed by
`factor_factory.hybrid_research.journal_adapter.run_hybrid_episode_from_request`.
Required fields are `report_id`, `run_id`, `handoff_stage` (`step2` or `step6`),
`fit_data` (`signed_impulses`, `observed_response`, `step`), `derivation_scope`
(the fields of `DerivationScope`), and `schedule_state` (`episode_index`,
`explore_allocations`, `exploit_allocations`). Use `split: development`; final
and confirmation inputs are rejected. `search_config` accepts `allowed_rates`,
`allowed_scales`, `seed`, `generations`, `population_size`, `max_evaluations`
and `max_attempts`. `response_semantics` optionally supplies `ResponseSemantics`
including explicit training/scoring indexes and initial-state conventions.
`implementation_evidence` optionally binds actual review/test evidence; missing
evidence stays missing and does not become an approval.

This GP fits supplied development observations. It is **not proposal-only** or
a general factor-expression grammar. `ResponseProgram` holds zero, one or two
`KernelTerm(scale, decay_rate)` terms; scope/response semantics constrain the
admissible family. It does not support arbitrary daily panel ASTs, relative-peer
returns, exact-calendar lags, or an activity-conditioned factor merely because
that factor uses multiplication. Use ordinary reviewed direct code or hybrid
implementation for unsupported mathematical objects; never reshape the object
or fabricate signed flow to fit this API.

The fit returns a selected candidate and an attempted/evaluated/rejected trace.
The journal binds input and artifact hashes and writes researcher material with
`computed_awaiting_researcher`, not approval. Reusing the same run/input resumes
saved material without fitting again; changed input under the same run is
rejected. An interrupted fit with unknown completion remains unknown instead of
automatically retrying. Nonfinite fit inputs are rejected, never filled with zero.
The adapter does not load a catalog, prove target maturity, produce a monthly
score panel, reserve cross-workspace market trials, or enforce a process memory/
disk quota. Callers must keep development inputs legally available, explicitly
bound fit sizes/budgets, and use the existing research trial accounting before
any return-scored search. A development fixture consumes no market-study slot.

### Restricted panel-expression search (R35 and later supporting releases)

`factor_factory.hybrid_research.threshold_gp.run_threshold_family_gp` supplies
an actual, bounded variation operator for the reviewed threshold-response
family: one categorical gene, one generation, at most two mutations. It emits
the signal and its paired price-alias control together; crossover is disabled
because the grammar is not closed under it. This is not open-expression or
fitness-driven multigeneration GP, and it does not replace the induction above.
Use only a Step2-reviewed family and the study's explicitly selected release.

`registered_program_search.run_registered_program_search` in the same package
evaluates an already materialized registry; it creates no mutations and must
not be reported as GP. Both routes require the caller's real development
evaluator, shared market-trial accounting and durable evidence. They neither
load market data nor dispatch Step3–6. Preserve attempted/rejected candidates,
seed, lineage, paired controls, known costs and unknown completion. Engineering
scores or Unknown callbacks do not demonstrate market efficacy. For GP/MCTS
comparisons, reused results remain reused evidence, not free independent trials.
See `docs/design/self-improvement-d04/amihud-r34-adapter-trial/README.md` in the
selected checkout; its historical R34 name is not the current release pin.

`run_action_mcts(enabled=True, evaluator=...)` is a library interface; its real
`ActionEvaluator(ResearchState, Action, seed) -> ActionResult` callback performs
the authorized action and returns an evidence-bound `Observation`. It has no
shipped monthly-market callback or Ultimate CLI dispatch. Missing callbacks
raise an error. In-memory cost/expansion limits do not replace durable market
trial reservations. The demo is synthetic engineering evidence only. RL is not
implemented. None of these interfaces establishes alpha or changes IS/OOS scope.
