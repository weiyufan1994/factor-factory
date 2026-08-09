---
name: factor-forge-miner
description: Run an isolated industrial factor-mining campaign using Data API catalogs, executable candidate programs, bounded cheap screens, controlled evolution, data-gap reporting, and a formal Ultimate research queue.
---

# Factor Forge Miner

## Role

Miner is the high-throughput candidate factory before Ultimate. It converts the
current Data API catalog, reusable datamarts, template functions and operators
into executable candidate populations, runs bounded IS screens, evolves diverse
survivors and writes a research queue.

Miner does not perform official Step1-6 research and cannot promote a factor.

## Workspace

Every campaign has exactly one isolated root:

```text
factor_research/miner/<campaign_id>/
```

All inventory, programs, materialized signals, screen evidence, evolution
generations, data requests and queue files remain inside it. Do not mix a Miner
campaign with baseline Step3, another factor workspace, a separate repo or
repo-root generated data.

Inspect repository/worktree state before starting. Never use `git add .`.

## Search Control

Before screening, author
`factorforge_miner_search_control_v1` with:

- canonical `data_split_manifest_ref` plus SHA256. The immutable
  `factorforge_miner_data_split_manifest_v1` binds campaign, universe, the exact
  IS source-panel hash/date range and every sealed OOS panel hash/date range;
- `selection_window_role=IS_SEARCH`, exact `selection_window_id`, universe and
  campaign identity;
- immutable materialized-panel `data_snapshot_hash`;
- sealed OOS token/hash equal to the canonical split-manifest SHA256;
- purge and embargo;
- zero-based `generation`, trial budget, cumulative `trials_used`, and unique
  ordered `tested_program_hashes` ledger;
- for every `generation>0`, workspace-local
  `previous_search_control_ref` plus its SHA256; the current tested-program
  ledger must equal the complete prior ledger followed by new hashes;
- implemented multiplicity policy `BH_FDR|holm_bonferroni` and
  `multiplicity_alpha` in `(0, 0.2]`;
- cost, impact, capacity, regime, universe and mask IDs.
- `factorforge_miner_cheap_screen_policy_v1` with decimal return units,
  preregistered send/keep IC, spread and long-end thresholds.

An accepted control is materialized once at
`objects/search_control/search_control__gNN.json`. Reusing that generation with
different contents is BLOCK. Later generations must reference this canonical
artifact, not an alternate history file.

OOS cannot enter generation, ranking, mutation reward or cheap-screen selection.
The candidate executor and every screen replay must prove that its source hash is
the registered IS hash and is not any registered OOS hash. A locally frozen hash
contract is tamper-evident campaign governance, not external secrecy or a trusted
timestamp. Cheap screen is exploratory evidence only.

## Campaign Workflow

### 1. Catalog-First Inventory

Build capability inventory from the active Data API catalog(s):

```bash
python3 scripts/build_factorforge_miner_capability_inventory.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --catalog <data_catalog.json>
```

Reuse cataloged datamarts and operators first. A missing state becomes a
workspace-local data-gap/data-request artifact; do not silently raw-scan a full
production minute window.

### 2. Freeze IS/OOS Split

Before candidate execution, materialize IS and sealed OOS panels inside the
campaign workspace and freeze their identities:

```bash
python3 scripts/write_factorforge_miner_data_split_manifest.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --is-panel <is_source_panel> \
  --is-window-id <fixed_IS_window> \
  --universe <universe_id> \
  --oos-panel <sealed_oos_panel> \
  --oos-window-id <sealed_OOS_window>
```

This writes the immutable canonical
`objects/search_control/data_split_manifest.json`. A different rewrite is
BLOCK. The registered OOS must remain `SEALED_UNRELEASED` while mining.

### 3. Candidate Population

Generate mechanism-tagged candidates:

```bash
python3 scripts/build_factorforge_miner_candidates.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --data-split-manifest <campaign_workspace>/objects/search_control/data_split_manifest.json \
  --inventory <inventory.json>
```

Each candidate must have its own executable program, output column, parameter
set, program hash, parent lineage, mechanism family, required inputs, added
degrees of freedom and expected failure mode. A shared placeholder signal is
smoke-only and queue-ineligible. Candidate and mutation manifests bind the
already-frozen split reference/hash; creating the split after candidate
generation is not a valid campaign lineage.

### 4. Data Gaps

```bash
python3 scripts/build_factorforge_miner_data_gap_report.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --candidate-manifest <manifest.json> \
  --inventory <inventory.json>
```

Separate `ready`, `needs_data`, `needs_operator`, `blocked_qa` and
`unsupported`. Do not reinterpret a missing input as zero or a proxy without a
new candidate identity.

### 5. Execute Programs

```bash
python3 scripts/execute_factorforge_miner_candidate_programs.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --candidate-manifest <manifest.json> \
  --source-panel <panel.csv|panel.parquet> \
  --data-split-manifest <campaign_workspace>/objects/search_control/data_split_manifest.json \
  --artifact-tag g00
```

The executor materializes candidate-specific columns and records source,
program and output hashes. Candidate/campaign identity, program hash uniqueness,
and expected factor-column identity are fail-closed. Non-mappable programs are
blocked. The source panel must be materialized inside the campaign workspace.
Keep the emitted `program_execution_report.json`; cheap screen replays every
program from the source panel and will not trust a matching hash alone.

### 6. Cheap Screen

```bash
python3 scripts/run_factorforge_miner_cheap_screen.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --candidate-manifest <executed_manifest.json> \
  --panel <materialized_panel.parquet> \
  --program-execution-report <program_execution_report.json> \
  --screen-window <fixed_IS_window> \
  --universe <universe_id> \
  --search-control <search_control.json>
```

Rank candidates using candidate-specific evidence. Include coverage, IC
stability, long-side direction, turnover/cost proxy, complexity, alias and
regime penalties. Preserve failures and mechanism-family diversity; do not keep
only the highest IC. The panel hash, campaign/window/universe identity and every
tested program hash must match the search-control ledger.

The screen computes a one-sided daily-IC p-value for every tested program and
applies the preregistered BH-FDR or Holm correction across the cumulative trial
family. Prior trial hashes absent from the current panel receive conservative
`p=1`. An unsupported label such as deflated Sharpe/PBO is BLOCK until a real,
tested implementation exists. A candidate that misses adjusted alpha may remain
an anti-pattern/diagnostic record but cannot enter the formal research queue.

Compute endpoints inside each date with value-based quantiles before aggregating
through time. Never pool stocks from different dates into one quantile sort or
split equal factor values by row order; a collapsed four-bucket cross-section
does not contribute endpoint evidence. `turnover_estimate` is the one-way
migration of cross-sectional signal percentile ranks, not the source stock's
`turnover` field. Miner ICIR is explicitly unannualized search diagnostics.

### 7. Evolve

```bash
python3 scripts/build_factorforge_miner_evolution_round.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --candidate-manifest <executed_manifest.json> \
  --cheap-screen-summary <summary.json> \
  --generation 1
```

Execute and screen the new generation again. Mutation must change an executable
program and produce a new hash. Renaming a candidate or changing prose is not a
mutation. Stop when budget is exhausted, diversity collapses, evidence is
dominated by aliases, or no survivor clears the preregistered queue gate.

### 8. Research Queue

```bash
python3 scripts/build_factorforge_miner_research_queue.py \
  --campaign-id <campaign_id> \
  --workspace-root <campaign_workspace> \
  --cheap-screen-summary <summary.json>
```

Each queued item must carry program/data hashes, search controls, mechanism
hypothesis, data requirements, cheap-screen evidence, known failure modes,
trial lineage, adjusted p-value/multiplicity family and replayed executor-report
lineage, plus the new isolated factor workspace to create. Queue construction
replays the candidate programs, all deterministic screen results and the
BH-FDR/Holm family before admitting an item; edits to the summary cannot create
a winner. Queue admission starts Ultimate research; it is not factor acceptance.

## Financial Boundaries

- Miner IC/ICIR are search diagnostics, not final proof.
- Fama-MacBeth and quintile/decile monotonicity belong to formal Ultimate only
  when the queued claim class is `risk_premium`.
- Transaction cost, volatility drag, capacity and long-end payoff must be
  re-established in the formal factor workspace.
- No reinforcement learning reward may consume sealed OOS or equal raw IC/PnL.
  Until verified trajectories exist, use deterministic population search and
  independent review.

## Acceptance

Before declaring Miner usable, run:

```bash
python3 scripts/run_factorforge_miner_mvp_smoke.py
```

The smoke must prove distinct programs produce distinct factor columns, mutation
changes executable programs, BH/Holm corrections match known values, forged
executor reports/panels fail replay, search controls are enforced, and queue
generation does not use OOS or production write paths.

## On-Demand Reference

Read `references/legacy-operations-reference.md` only for the original template
catalog, detailed artifact schemas, Data API mappings and compatibility notes.
