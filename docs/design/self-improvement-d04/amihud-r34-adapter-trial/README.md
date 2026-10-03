# Amihud R34 registered GP/MCTS adapter trial

Base release commit: `e6d4e647b82abe275ab49a6e84a8fc8c0c3c8b50`.

The original R34 response GP is a valid but narrow signed-impulse response
grammar.  It cannot represent the reviewed Amihud panel statistic
`D*c`.  `registered_program_search.py` adds a separate finite-registry
evaluation route for research
objects like this one.  Every expression must be materialized before the call,
hash-bound to its mathematical object, assigned explicit lineage and cost, and
evaluated only through development evidence.  The routine cannot create a new
formula, retry an unknown-cost exception, turn Unknown into reward, or consume
final/OOS evidence.

This route is intentionally smaller than open genetic programming.  It does
not execute mutation or crossover; those operations are only accepted as
reviewed lineage on already materialized programs.  In the current three-shape
dry run, actual mutation count and actual crossover count are therefore both
zero.  Calling finite enumeration or score sorting “GP improvement” would be
incorrect.  The adapter is the evidence/budget boundary needed before a later
reviewed variation operator can be connected.

The follow-up `threshold_gp.py` is that separate typed variation operator.  It
starts from the reviewed uniform-threshold gene and actually materializes the
two reviewed neighboring genes at runtime.  Signal and exact price-alias
control are emitted together.  Arbitrary expressions and unreviewed threshold
families cannot enter the grammar.  Crossover remains disabled with an explicit
`grammar_not_closed` reason because crossing the two Beta endpoints can create
an unreviewed family.

`typed_threshold_gp_engineering_trial_v1.json` is the seed-20261003 execution:
two mutation attempts, two materialized mutations, zero crossover attempts,
three common-budget callback calls, and zero market evaluations.  Its equal
readiness scores test grammar/hash/alias binding only.  The reported baseline
selection is a complexity tie-break and has no economic meaning.

The registered-program layer also retains every valid known `actual_cost` when
an evaluator result violates identity or reservation.  A wrong return type is
recorded once as a contract violation with unknown cost and stops without a
retry.  `spent_cost` is then the known subtotal, never a claim that total cost
was zero.

`adapter_trial_v1.json` records an actual seed-20261003 invocation against the
current reviewed D*c identity and source hashes.  Both GP and enabled MCTS each
called their callback once.  The callback returned Unknown at zero cost because
the current Step2 freezes a single D*c estimand and authorizes neither a second
formula nor a development market score for this engineering trial.  The GP
therefore reports
`no_eligible_development_evidence:single_registered_program`; MCTS records one
unknown expansion.  Market rows read and campaign trials consumed are both
zero.  This proves interface and provenance binding, not factor fit, algorithm
superiority, or market evidence.

The first three-program dry run also exposed a shipped MCTS defect: three
Unknown development observations still produced a root `selected_action_id`.
The patch now marks a node as development evidence only when
`learning_increment()` is available, and root recommendation requires that
state explicitly.  The rerun retains all three Unknown calls and returns no
selection.  `test_unknown_development_observation_cannot_become_a_recommendation`
is the direct regression; the existing positive-reward tests remain the
counterexample proving eligible evidence can still select.

Minimal call shape:

```python
result = run_registered_program_search(
    programs=reviewed_programs,
    evaluator=development_evaluator,
    metric="joint_gate_development_score",
    direction=1,
    seed=20261003,
    total_budget=reserved_budget,
    max_evaluations=len(reviewed_programs),
)
```

A substantive GP run now requires a separately reviewed finite candidate
registry.  A substantive MCTS run requires a real evaluator that returns the
same registered development metric and durable evidence after reserving one of
the shared campaign slots.  The existing simple scheduler can use the same
actions/evaluator/budget for a paired comparison; it must not receive free
duplicate market calls.
