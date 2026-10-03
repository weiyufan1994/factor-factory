# MCTS Unknown-selection defect found by the Amihud dry run

The first enabled three-program call used seed `20261003`, zero-cost actions,
and three real callbacks.  Every callback returned a development Observation
with `status="unknown"`, `result=None`, and `learning_increment() is None`.
R34 nevertheless returned
`selected_action_id="evaluate__amihud_linear_D_c"` after three expansions.
No market rows or campaign trials were consumed.

Cause: child nodes set `development_evidence=True` for every new development
record, even when the record carried no learnable increment.  Root
recommendation admitted every child whose flag was not explicitly false, so
Unknown could win a zero-valued tie.

Fix: set the flag from `increment is not None` and require it to be exactly
true in `_recommend_root_action`.  The same call was rerun and now returns
`selected_action_id=None`; the updated full trace is in
`proposed_neighborhood_dry_trial_v1.json`.  The focused Unknown regression and
the existing positive-evidence selection tests both pass.
