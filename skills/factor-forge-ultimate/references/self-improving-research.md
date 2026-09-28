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

`factor_factory.hybrid_research` may summarize comparable development evidence
and recommend a registered action. It does not execute actions, create a
mechanism, validate semantics, write canonical knowledge, or replace Step2 code
review. Its normalized delta is local to the stated metric and protocol, not an
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
