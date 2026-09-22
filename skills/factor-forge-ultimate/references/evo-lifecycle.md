# EVO V2 lifecycle and authority

Read only when the frozen conjecture enables EVO V2, or for an authorized incident/recovery task. This is not a prerequisite for ordinary local IS.

## Epistemic Evolution V2

Read and apply
`docs/contracts/factorforge-epistemic-evolution-v2.zh-CN.md` whenever the
research conjecture enables `factorforge_epistemic_evolution_policy_v2`.
Treat EVO as constitutional invariance plus epistemic evolution, never as an
Agent-controlled Skill editor, score optimizer, or canonical-memory writer.
Do not let any Agent change the estimand, measurement program, thresholds,
OOS policy, multiplicity, trial budget, validator, role permissions, or
canonical-write authority.

For an EVO-enabled Web run, use the normal Ultimate wrapper. After Step4 the
wrapper must materialize only the purged-IS diagnostic checkpoint and return
`PAUSED / AWAITING_EVO_V2_HOST_QUALIFICATION`; it must not release OOS or
qualify its own contradiction. Resume according to the Host-admitted lifecycle:

- `NO_QUALIFIED_CONTRADICTION`: release OOS once for the original candidate,
  then forbid parent revision/Council handoffs;
- `QUALIFIED_CONTRADICTION`: run the real Agentic Council on `PURGED_IS_ONLY`,
  with OOS still sealed;
- `MINIMAL_MECHANISM_DELTA`: record the Dirac-style smallest extension and
  economic backprojection as review-only;
- `NO_DERIVED_LAW`: terminate as kill-and-learn without fabricating a law;
- `TRANSFER_RECORDED|COLD_START_RECORDED`: remain paused for external human
  approval and a separately preregistered child with fresh sealed OOS.

Only the Host may advance the signed append/CAS lifecycle:

```bash
python3 scripts/record_factorforge_evo_v2_lifecycle.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --to-state <next_state> \
  --evidence-ref '<hash-bound-verifier-reference-json>' \
  --expected-parent-sha256 <prior-lifecycle-payload-sha256> \
  --trust-root <host-private-runtime-trust-root> \
  --installation-id <installation_id>
```

Materialize Agent-authored semantics only through the staged writer, in order:
`admit-feedback -> admit-council-outcome -> admit-transfer -> record-use`.
Pass both lifecycle CAS hashes and the previous staging manifest content hash;
use `ABSENT` only for the first stage. Never use `full-bundle` to prewrite future
artifacts. See the EVO contract for the complete commands and the distinct
`NO_DERIVED_LAW` terminal path.

After a minimal delta, keep the run paused. Only after the signed lifecycle has
reached `TRANSFER_RECORDED` or `COLD_START_RECORDED` and the staged writer has
completed the exact four events through `record-use`, invoke the signed
external-human pre-OOS bridge:

```bash
python3 scripts/approve_factorforge_pre_oos_child.py \
  --workspace-root <factor_workspace> --report-id <parent_report_id> \
  --human-approval-receipt <signed-external-human-receipt.json> \
  --human-trust-manifest-sha256 <out-of-band-manifest-pin> \
  --host-trust-root <host-private-runtime-trust-root> \
  --installation-id <installation_id> \
  --incident-trust-root <host-private-runtime-trust-root> \
  --incident-installation-id <installation_id>
```

The signer pair and incident pair must name the same canonical trust-root path
and installation identity. One live incident guard spans lineage replay, all
three semantic projections, ticket signing, and readback.

The repository does not generate the human key or receipt, and the bridge does
not materialize or execute the child. It consumes the canonical pre-OOS outcome,
selected raw Agent result, staged delta/backprojection, external Ed25519 receipt
and fresh child OOS allocation to write only closed approval, handoff and child
intent semantic projections, plus a Host-signed non-ready authorization ticket
for the isolated authoring/preregistration chain. It may additionally project a
`MATERIALIZATION_READY` ticket only when a complete child preregistration
receipt already exists and passes strict replay. Neither ticket materializes or
executes child inputs; no Step5/6 research iteration is required or fabricated.
At `MINIMAL_MECHANISM_DELTA` it must return
`WAITING_FACTORFORGE_EVO_TRANSFER_USE_RECORD` instead of approving early.
Before child materialization, an isolated Agent authoring session must produce
the child research state, conjecture, approach registry, base trial ledger and
report-scoped Web plan. The Host may admit and mechanically project those
semantics, but must not author them. An independent reviewer then issues the
truthful revision-child assurance; strict preregistration freezes the projected
ledger, metric verifier, threshold and Web proof controls. Missing controls must remain
`WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION`; do not copy an ancestor/sibling OOS
window or token.

Production child execution follows the exact signed chain
`AUTHORING_ADMITTED -> CHILD_PREREGISTERED -> MATERIALIZATION_READY ->
CHILD_MATERIALIZED -> POST_MATERIALIZATION_ADMITTED -> CONTAINER_ADMITTED ->
CHILD_EXECUTION_READY`. `revision-child-assured` is the honest two-role child
assurance mode; it must never be represented as a child seven-role
`formal-complete` runtime. Only `run_step3b`, `validate_step3b`, `run_step4` and
`validate_step4` execute in the no-network admitted child container. Host
prefetch and the OOS finalizer remain outside it, and neither carrier, locator,
Host trust/state nor data credentials may be mounted into an Agent stage.

Crash recovery is receipt-driven. `CHILD_RESUME_READY` resumes only the signed
4/5/6 checkpoint, `CHILD_RECOVERY_READY` is finalizer-only, and a `RUNNING`
proof may continue only through a Host-signed exact-next-command admission
binding its proof snapshot, latest container termination, inflight attempt and
immutable prefetch receipt. Descendants repeat the complete chain and replay
every signed `HOST_CHILD_HANDOFF` edge in the root-to-active lineage. Wrapper
`PASS` and ordinary `CHILD_TERMINAL` never imply factor acceptance; only the
validated `EVO_CHILD_TERMINAL_CHECKPOINT` may carry `ACCEPT|REJECT`.

If any unauthorized read or derived artifact overlaps a frozen OOS window,
record it immediately with
`scripts/record_factorforge_oos_exposure_incident.py`. The public create-only
marker and the Host-private signed append-only negative registry carry no
release or verdict authority: they permanently set `formal_oos_eligible=false`.
Marker presence alone—including malformed content, a directory, or any
symlink—must block allocation, preregistration, release, finalization and
consumption. Deleting the public marker must not clear the Host registry, and a
valid incident replay does not restore OOS authority. If the original runner
bytes were not frozen, use the provenance addendum to label current code
`CURRENT_REMEDIATION_RECONSTRUCTION_ONLY`; never present it as incident-time
lineage. Scan every root-to-active ancestor so a descendant identity cannot
launder an exposure incident.

Use the complete Host-current command; the fixed timestamp is part of exact
idempotent replay:

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

Replay the same explicit Host pair at every current-authority boundary from
`AUTHORING` through `PREREGISTERED`, `READY`, allocation, release/consume and
terminal closure. Formal mutations keep the lineage check, write and readback
inside one live incident guard. Agent structural replay has no Host secret and
must expose `current_formal_authority_verified=false`.

Keep the tension ledger split by layer: record predicted/observed signatures,
mismatch vector, rival explanations, next discriminating test,
`what_survived`, and `what_failed`. Retrieve experience only after blind
derivation by mechanism fingerprint. Treat market state and historical events
as provenance-bearing stress coordinates, not as a regime router, and require
an actual before/after question/test change receipt before claiming transfer use.

Keep assurance meanings separate. EVO validator PASS does not imply a valid
Council proposal, factor-proof ACCEPT, memory review approval, canonical memory
promotion, external human approval, or child execution authority.
