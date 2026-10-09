# Hosted domain-proposal format

Read for an actual signed organization task, not an ordinary Step2 advisory question.
The task packet supplies identity, allowed inputs/output path and frozen scope.

## Output Contract

Read [the result example](domain-research-proposal-v1.example.json)
before authoring. The envelope has exactly these required bindings:
`task_ref`, `identity`, `role_id`, `status`, `producer_mode`, `session_id`,
`public_research_record`, and `result_sha256`. Copy task identity and hashes from
the assigned `factorforge_agent_task_v1`; compute `result_sha256` over the full
envelope excluding `result_sha256` itself.

The nested proposal uses one of:

- `ready_for_director_review`
- `under_specified`
- `awaiting_data`
- `out_of_domain`

Map these to envelope status `PASS`, `NEEDS_CLARIFICATION`, `NEEDS_DATA`, or
`BLOCK`, respectively. Write the envelope only to the Host-provided private
candidate path. Do not write the workspace result path directly. The Host
validates and atomically admits it to
`objects/research_organization/<report_id>/results/<role_id>.json` with
`scripts/admit_factorforge_agent_result.py`. The proposal is not the canonical
measurement program and may not modify Step artifacts, data, code, knowledge,
or another Agent's result.

Bind every cited staged input in top-level proposal `artifact_refs`. Each item
has exactly two keys, `path` and `sha256`, copied from the matching
`runtime_context.json.files` entry. Do not copy context-only metadata such as
`size_bytes`. Every optional role-memory candidate may cite only these exact
two-key references.

Set `producer_mode=real_agent` only for an actual isolated Agent session with
its real unique `session_id`. Current v1 tasks set
`single_agent_fallback_allowed=false`; the main/Host session therefore must not
submit this specialist result. If a later frozen task explicitly permits
fallback, use `producer_mode=single_agent_fallback` with the actual host/main
`session_id`; never mint an isolated-looking id or claim independence, review,
or Council authority.

## Hard Boundaries

- Do not change the hypothesis, estimand, horizon, or information set.
- Do not run production research, generate data, or approve promotion.
- Do not treat backtest strength as proof of the mechanism.
- Do not conceal uncertainty, identification gaps, or proxy error.
- Do not merge your own proposal into canonical artifacts.
- Do not let `single_agent_fallback` impersonate an independent session or
  Council verdict.
