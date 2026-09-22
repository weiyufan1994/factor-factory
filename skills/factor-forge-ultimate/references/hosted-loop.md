# Hosted child loop

Read only for an authorized hosted child-loop execution. Ordinary local IS continues with the Ultimate wrapper, not this loop CLI. Child approval remains a separate gate.

### Default Loop Objective

The default research objective is to run the formal Factor Forge path through
Step6, let Council decide promote/reject/revise, and continue through guarded
child-report revision loops until one of these stop conditions is reached:
`promote_official`, validated no-derived-revision proof blocks further work,
evidence/case comparison blocks further work, or 10 Council revision loops have
been reached.
At the 10-loop cap, if the factor is still not promotable but Council believes
substantial upside remains, stop and report the state to the user instead of
silently continuing.

### Ultimate Loop Orchestrator

`scripts/run_factorforge_ultimate_loop.py` is the thin Phase M orchestrator above
the existing official wrapper. It must call `scripts/run_factorforge_ultimate.py`
for every formal pass and must not call Step1-6 scripts directly.

A formal non-dry loop invocation must provide the same explicit Host incident
identity used by every nested Ultimate pass:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <root_report_id> \
  --incident-trust-root <host-private-incident-trust-root> \
  --incident-installation-id <host-installation-id> \
  <remaining-loop-arguments>
```

Do not replace these loop flags with `--host-trust-root`; the latter belongs to
the release/verifier/incident CLIs. The loop passes the validated pair into its
nested formal wrapper environment and every current child materialization.

The loop runner writes:

- `objects/runtime_context/ultimate_loop_report__{root_report_id}.json`
- `objects/runtime_context/ultimate_loop_brief__{root_report_id}.md`

`orchestrate_factorforge_evo_pre_oos_outcome.py`,
`orchestrate_factorforge_evo_transfer_use.py`, and
`materialize_factorforge_web_evo_is_checkpoint.py` are Host-only transaction
helpers invoked by the wrapper/Console. They are not alternate production
entry points; direct use is reserved for debugging the corresponding Host
transaction with every required trust, installation, and frozen-hash argument.

It stops on promotion, true factor rejection, blocked evidence/prewrite state,
Council script checkpoint `awaiting_agent_results`, `awaiting_next_derivation`,
wrapper failure, missing approved child revision, forbidden side effects, or the
10-loop cap. It may continue to a child report only when a validated
`handoff_to_step3b__{report_id}.json` explicitly authorizes
`approved_for_step3b_handoff`; child report ids must be derived from the parent
as `{parent}__LOOPNN__{revision_id}`. A failed child branch before max loops is
`revision_branch_only` falsification, not factor-level rejection, unless Council
provides validated terminal authority. The orchestrator itself must not write
Step3B handoffs, official records, generated code, clean data, or search-worker
outputs.

At the skill level, `awaiting_agent_results` must be handled by autonomous
Council continuation above. The agent should not present it as the final answer
to the user unless it is technically unable to create valid Council results in
the current runtime.
