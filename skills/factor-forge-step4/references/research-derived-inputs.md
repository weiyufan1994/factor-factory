# Research-derived inputs for local IS

Read when standard Data API observations suffice for an estimator but no
published derived table represents it. A reviewed research adapter may prepare
the exact state in its study workspace. Data owns the source service; research
owns the mathematical transformation. A shared catalog release for that
study-local state is not a prerequisite.

## Choose the observation, then the route

Use a published derived dataset when its actual fields, information time and
missingness preserve the reviewed estimator. Otherwise bind standard source
fields and explicitly prepare the estimator-specific state. For example, daily
flow totals do not recover minute trend-conditioned state returns. Renaming
those totals or inferring the missing returns changes the mathematical object.

The legacy ordinary minute snapshot builder automatically attaches
`minute_derived_flow_state_v1`. Do not treat that generated requirement as a
semantic decision. For a different state use the existing prepared route below
and regenerate the Step3A/handoff binding after review; do not delete a blocker
from an old handoff or enable generic raw streaming in Step4.

In the new prepared declaration, `local_inputs.step4_data_contract` must not
inherit an inapplicable `minute_derived_state_requirements` from the old route.
That field describes shared catalog dependencies, not controller-owned local
state. Bind the local schema and provenance in the reviewed controller config.
With no shared dependencies the resolver emits `no_state_required`; this does
not validate the prepared state or waive its consumer checks.

## Bind and review the adapter

Record the following in the existing spec, data preparation/handoff and
implementation artifacts. No new platform registration or approval layer is
required.

- Source API dataset/version, selected fields and query, catalog file/hash,
  source object/content identity, calendar and universe; reuse published source
  acceptance and document any observed gap rather than recertifying the API.
- The derived observation schema: keys, units, missing/zero semantics, state
  definitions and the mapping to the estimator. Bind preparation and consumer
  code hashes, including invoked helpers, and partition/content hashes.
- Information availability and signal/trade timing. Each factor value uses
  only observations available by its declared signal time. Full-session bars
  can support an after-close signal traded later; they cannot support an
  earlier intraday decision. A generic `14:50` default must not override a
  reviewed after-close specification. Future labels stay in evaluation.
- Coverage and replay evidence: expected sessions, actual partitions, gaps,
  duplicate keys, unavailable states, rolling warmup and relevant cross-section
  coverage. A missing state is not automatically a zero or a missing session.
  Preserve the measurement universe; apply the declared PIT
  `tradability_risk_flags_daily` join in evaluation, without silently changing
  the cross-section used to construct the factor.

The consumer validates its bound schema, identities, dates and coverage before
using the state; fail on unbound/mismatched fields or stale artifacts. Retain
the existing Step2-independent code review and post-review tests for the actual
adapter and helpers. Schema labels and `no_future=true` declarations alone are
not proof. Test reference-versus-derived parity, future-data mutation, rolling
overlap and chunk boundaries, row/index reordering invariance, and relevant
missing/invalid-input counterexamples. Row labels must not change numeric
alignment or the measurement cross-section when partitions are combined.
If the observation map, estimator or timing changes, resolve it in Step2; a
storage refactor does not authorize a different factor.

## Prepare once and use the existing entrypoints

Perform source reads and state preparation as an explicit bounded research
task outside the factor class and Step4 evaluator. Use the standard Data API,
the declared sample/window, date partitions, selected columns, checkpoint/resume
and hashes. Preserve the source receipt and an executable replay command. Reuse
matching prepared partitions; invalidate affected partitions when source,
calendar, schema, cutoff or producer code changes. Do not repeat full raw reads
inside each formula revision.

The existing local-IS route is:

1. Pass `--prepared-local-inputs` to Step3/Ultimate, with
   `input_mode=derived_state_with_daily`, full `daily_df_parquet`,
   `derived_state_root`, `sample_window_actual`, and either `calendar_dates` or
   `run_config_path`. Paths must name the declared study artifacts.
2. Declare separate bounded Step3B inputs: `step3b_daily_df_parquet`,
   `step3b_derived_state_root`, `step3b_sample_window`, and either
   `step3b_calendar_dates` or `step3b_run_config_path`. Also provide the explicit
   `step3b_prepared_controller_config` consumed by Step3B; it must bind only the
   sample paths/calendar and its controller's applicable sample budget.
3. Bind the reviewed `compute_factor_partitioned` controller. It receives the
   prepared state/daily paths and writes the Step-owned `output_path`; the
   ordinary factor/metrics output schemas stay unchanged. It must not fetch
   raw source data or labels. Controller-owned validation checks the declared
   state schema and provenance; the framework hook itself does not infer them.
4. After the existing version-bound review and tests pass, resume Ultimate at
   Step4 with `--local-is-only`. Step4 consumes the full prepared input binding,
   produces formal values and invokes the selected existing evaluator. Step3B
   sample values remain executability evidence only.

This route is already supported by the runtime. It is local-IS-only; it does
not bypass OOS/Host or promotion rules. A research-specific adapter is ready
only when its own reviewed code, input scope and evidence are ready. Publishing
this guidance does not certify an unfinished adapter or its factor results.
