# Step6 EVO V2 and child authority

Read only for the frozen EVO V2 route or an authorized child/incident/recovery action, together with [Ultimate lifecycle](../../factor-forge-ultimate/references/evo-lifecycle.md). Local judgment does not activate this route.

## EVO V2 Pre-OOS Contradiction Path

When the conjecture enables EVO V2, read
`docs/contracts/factorforge-epistemic-evolution-v2.zh-CN.md` and do not apply
the normal post-Step5 revision flow to that parent. Run revision Council only
after the Host admits `QUALIFIED_CONTRADICTION`, using the purged-IS checkpoint
and canonical feedback ledger. Require `uses_oos=false`, `PURGED_IS_ONLY`,
complete lower-layer clearance, a preregistered materiality breach,
multiplicity/trial-budget compliance, and at least two rival models. A large
residual, high IC/Sharpe, historical score, or Council majority is not
qualification.

Maintain a tension ledger instead of one scalar score. Preserve predicted and
observed signatures, mismatch vector, failure layer, rival explanations, next
discriminating test, `what_survived`, and `what_failed`. Keep a Rank IC that
survived distinct from after-cost long-side economics that failed.

For a qualified contradiction, accept exactly one of:

- `MINIMAL_MECHANISM_DELTA`: add one smallest identifiable object, show
  zero-extension recovery, preserved/broken invariants, information deleted,
  a unique prediction, distinguishing test, complexity cost, and why larger
  extensions were rejected; then backproject it to actor, action, constraint,
  payer, receiver, payoff/profit transfer, persistence, capacity, proxy,
  negative control, counterfactual and disappearance condition;
- `NO_DERIVED_LAW`: state the identification/budget blocker and terminate the
  branch without a child.

Do not force DCF or any other model family. Select DCF, residual income,
accounting identities, stochastic, spectral, causal, functional,
microstructure, optimization, or a new composition only when the frozen
economic hypothesis requires it.

Keep Council output review-only. The Host advances lifecycle and staged CAS;
Council Agents cannot write canonical EVO artifacts. Run
`scripts/write_factorforge_evo_v2.py --stage admit-council-outcome` only after
the signed lifecycle reaches `MINIMAL_MECHANISM_DELTA` or `NO_DERIVED_LAW`.
Never prewrite transfer/use artifacts to make a future-stage validator pass.

Retrieve experience only after blind derivation, using the mechanism
fingerprint rather than historical return, market-state label, or event name
as the ranking key. Require structural-isomorph, cross-math analogy, near-miss,
counterexample and episode-context lanes plus source-to-target mappings. State
and events are falsification/stress coordinates only unless state dependence
was frozen in the current economic model. Do not claim transfer use until a
Host receipt binds the actual before/after research questions or tests.

The preceding command and `--approval-source` are only for the legacy/post-Step6
path. Do not use them for an EVO V2 pre-OOS revision. An EVO V2 pre-OOS
`MINIMAL_MECHANISM_DELTA` is not approvable yet: first require the signed
lifecycle to reach `TRANSFER_RECORDED` or `COLD_START_RECORDED` and require the
staging manifest to contain the exact four-event sequence through `record-use`.
Then use `scripts/approve_factorforge_pre_oos_child.py`. That bridge replays the
canonical pre-OOS outcome, selected raw Agent result, staged delta and economic
backprojection, external Ed25519 receipt, trust-manifest pin and fresh child OOS
registry allocation without requiring or fabricating a Step5/6 research
iteration. It writes the closed approval, handoff and child-intent semantic
projections plus a Host-signed non-ready authorization ticket for the isolated
authoring/preregistration chain. A `MATERIALIZATION_READY` ticket is permitted
only when a complete child preregistration receipt already exists and passes
strict replay. Neither ticket materializes or executes the child. The external
human receipt must bind the selected law, delta/backprojection, exact child
identity and a Host-provisioned fresh sealed OOS allocation; the repository
validates it but does not generate the human key or signature.
The Host invocation must also pass `--incident-trust-root` and
`--incident-installation-id`; they must exactly equal the canonical
`--host-trust-root` and `--installation-id` binding so one live guard covers
lineage validation, projection writes, ticket signing, and readback.

For EVO V2, preregister the child as a new identity before materialization and
bind a fresh sealed OOS allocation in the Host append-only registry. Missing
child conjecture/approaches/trial ledger/threshold/allocation must return
`WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION`. Never copy or overlap an ancestor or
sibling OOS token/window, and never reuse consumed OOS under a new name.

Do not let the Host fabricate the child research semantics. An isolated Agent
must author research state, conjecture, approaches, base trial ledger and the
report-scoped Web plan; Host admission and preregistration may only perform
closed-schema validation and deterministic projection. Before a READY ticket,
require the signed authoring admission, independent revision-child assurance,
strict preregistration receipt and exact frozen refs. Production execution must
then pass the seven signed stages `AUTHORING_ADMITTED -> CHILD_PREREGISTERED ->
MATERIALIZATION_READY -> CHILD_MATERIALIZED -> POST_MATERIALIZATION_ADMITTED ->
CONTAINER_ADMITTED -> CHILD_EXECUTION_READY`.

Each descendant repeats the same pre-OOS gate and receives a fresh allocation.
Recursive execution must persist and replay every signed `HOST_CHILD_HANDOFF`
phase receipt and the complete root-to-active lineage; a mutable current-row
pointer is not lineage authority. Container command recovery and finalizer-only
recovery are Host runtime concerns and may not be inferred from a Council
decision or a merely present child workspace.

An unauthorized read or local computation that overlaps frozen OOS is a
permanent negative authority event, not an informal warning. Record it through
`scripts/record_factorforge_oos_exposure_incident.py`, then bind the public
create-only marker into the Host-private signed append-only incident registry.
Any marker entry—even malformed or symlinked—and every registered incident on
the root-to-active lineage blocks child allocation/preregistration and all OOS
release/finalizer/consume paths. Deleting or repairing the public file never
restores eligibility. A successful validator only authenticates the negative
record; it cannot issue release, consumption, `ACCEPT`, or `REJECT` authority.

The formal incident command must include the exact Host identity and fixed
incident time:

```bash
python3 scripts/record_factorforge_oos_exposure_incident.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --factor-id <factor_id> \
  --frozen-oos-start <YYYY-MM-DD> --frozen-oos-end <YYYY-MM-DD> \
  --frozen-oos-release-token-sha256 <sha256> \
  --exposed-overlap-start <YYYY-MM-DD> --exposed-overlap-end <YYYY-MM-DD> \
  --exposed-row-count <count> --exposed-period-count <count> \
  --source-path <source> --panel-path <panel> \
  --metrics-path <metrics> --runner-path <runner> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id> \
  --incident-at <UTC_ISO8601_Z>
```

If a pre-existing public marker was created before durable Host registration,
bind it to the external signed negative registry without rewriting the marker:

```bash
python3 scripts/register_factorforge_oos_exposure_incident_host_private.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

If the original runner bytes were not frozen, keep the incident immutable and
append the explicit reconstruction-only correction. Reuse the fixed timestamp
for exact idempotent replay:

```bash
python3 scripts/record_factorforge_oos_exposure_provenance_addendum.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --correction-at <UTC_ISO8601_Z>
```

Both recovery commands preserve `NEGATIVE_EVIDENCE_ONLY` and
`formal_oos_eligible=false`; neither restores release, consumption or factor
verdict authority.

The same explicit Host pair is replayed at each current-authority boundary
from `AUTHORING` through `PREREGISTERED`, `READY`, allocation, release/consume
and terminal closure. Agent structural replay remains non-formal and reports
`current_formal_authority_verified=false`.

For standalone Host debugging of the child preregistration boundary, formal
`validate`, `materialize`, and `validate-receipt` require the incident-specific
pair explicitly; projection subcommands remain structural-only:

```bash
python3 scripts/preregister_factorforge_evo_child.py <validate|materialize|validate-receipt> \
  --workspace-root <factor_workspace> \
  --parent-report-id <parent_report_id> \
  --child-report-id <child_report_id> \
  --expected-host-trust-manifest-sha256 <out_of_band_sha256> \
  --incident-trust-root <host-private-incident-trust-root> \
  --incident-installation-id <host-installation-id> \
  <subcommand-specific-control-arguments>
```
