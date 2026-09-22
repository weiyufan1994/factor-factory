# Factor Forge Performance Production Closeout

Generated at: 2026-06-02

Branch: `codex/factorforge-performance-production-closeout`

Base SHA: `ea4d1418bed3e1deaee885b95730b0eebfd80525`

## Mac Proof

Status: `BLOCK_REAL_MAC_REPORT_NOT_PROVIDED`

No human-approved real report/run id was supplied for this closeout turn. I did not run an unbounded formal research job and did not start any worker. The non-environmental Mac proof is therefore synthetic `/tmp` smoke only:

- Summary: `/tmp/factorforge_performance_closeout_smoke/performance_smoke_summary.json`
- Verdict: `ACCEPT`
- `canonical_pollution=false`
- Case `real_run_performance_metadata_contract`: `ok=true`

The synthetic case exercises Step3B `generate_first_run_factor_values()` and Step4 on the same fixture, then checks:

- `performance_profile.version=factorforge_step3b_performance_profile_v1`
- `performance_profile.formula_kernel_profile.default_numpy_ts_profile.enabled=true`
- numeric `performance_profile.phase_seconds.compute_factor`
- parquet input selection
- `step4_factor_io_profile.version=factorforge_step4_factor_io_profile_v1`
- parquet formal factor selection
- boolean `step4_factor_io_profile.recomputed_factor`

## EC2 Proof

Status: `BLOCK_EC2_WORKER_NOT_APPROVED_OR_UNAVAILABLE`

This task did not have approval to start EC2 worker execution. I did not launch Step3B/Step4 on EC2 and did not run production research. EC2 proof remains blocked until a specific report/run id and worker-start authorization are provided.

## Runtime Branch Reconciliation

Status: `LOCAL_RUNTIME_SMOKE_ACCEPTED`

Read-only classification found remote runtime branch:

- `origin/humphrey-ec2/factorforge-step3-step4-data-api-runtime`
- Runtime SHA before merge attempt: `f09c1327756dad1464f76358f41691bd1d6c61a2`
- `origin/main`: `ea4d1418bed3e1deaee885b95730b0eebfd80525`

I created `/tmp/factorforge-ec2-runtime-reconcile` and attempted `git merge origin/main`. Merge conflicts occurred only in:

- `skills/factor-forge-step3/scripts/run_step3b.py`
- `skills/factor-forge-step4/scripts/run_step4.py`

Following the plan, those conflicts were resolved by taking `origin/main` for Step3/Step4 computation semantics. Smoke then showed runtime reconciliation is not ready to push:

| Check | Result | Evidence |
| --- | --- | --- |
| `py_compile` scoped runtime/control scripts | PASS | command rc=0 |
| `run_factorforge_v2_control_plane_smoke.py` | PASS | `RESULT: PASS` |
| `run_factorforge_entrypoint_hygiene_smoke.py` with `/tmp` root | BLOCK by policy | `BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN` |
| `run_factorforge_entrypoint_hygiene_smoke.py` with staging root | BLOCK | registry missing `scripts/run_factorforge_v2_control_plane_smoke.py` |
| `run_factorforge_run_isolation_smoke.py` | BLOCK | summary `/Users/humphrey/.factorforge-smoke/runtime_reconcile_isolation/objects/validation/factorforge_run_isolation_smoke_summary.json` |
| `run_factorforge_formal_artifact_smoke.py` | ACCEPT | summary `/tmp/factorforge_formal_artifact_smoke_summary.json` |

Follow-up verification on the closeout branch showed the prior smoke failures are no longer current for the branch being reviewed:

| Check | Result | Evidence |
| --- | --- | --- |
| `run_factorforge_entrypoint_hygiene_smoke.py` with staging root | ACCEPT | `/Users/humphrey/.factorforge-smoke/runtime_reconcile_hygiene_current` |
| `run_factorforge_run_isolation_smoke.py` with staging root | ACCEPT | `/Users/humphrey/.factorforge-smoke/runtime_reconcile_isolation_current/objects/validation/factorforge_run_isolation_smoke_summary.json` |

This closes the local runtime-smoke blocker for the branch. It does not by itself prove Humphrey production or research-worker execution, because no EC2 worker was started and no production runtime repo was synced in this closeout verification.

## Default Acceleration Evidence

Current production baseline already defaults the following NumPy TS kernels:

- `min`
- `max`
- `delta`
- `delay`
- `argmin`
- `argmax`
- `ts_rank`
- `correlation`
- `corr`
- `covariance`

Rollback env:

- `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1`

Explicitly excluded by current baseline:

- `std`
- `stddev`

Additional policy from inventory:

| Operator / Engine | Policy | Reason |
| --- | --- | --- |
| `ts_min`, `ts_max`, `ts_delta`, `ts_delay`, `ts_argmin`, `ts_argmax`, `ts_rank`, `rolling_corr`, `rolling_cov` | `default_enabled` | already included in `DEFAULT_NUMPY_TS_OPERATORS` |
| `ts_sum`, `ts_mean` | `opt_in_only` | not default-enabled on current production baseline |
| `ts_std`, `ts_stddev` | `blocked_by_edge_case` | excluded from current default set |
| `polars_formula_engine` | `opt_in_only` | experimental engine only |
| `experimental_formula_kernel` | `opt_in_only` | experimental engine only |

Smoke evidence:

- Case `operator_default_policy_is_explicit`: `ok=true`
- Default-enabled observed: `rolling_corr`, `rolling_cov`, `ts_argmax`, `ts_argmin`, `ts_delay`, `ts_delta`, `ts_max`, `ts_min`, `ts_rank`
- Non-default operators require `blocking_reason`
- Default-enabled operators require rollback env

## Reuse Evidence

Step3B now writes a reusable compute-cache identity and cache parquet:

- `step3b_sample_factor_values__<report_id>.parquet`
- `step3b_sample_run_metadata__<report_id>.json`

The identity includes:

- `producer`
- `is_formal_factor_values`
- `report_id`
- `factor_id`
- `implementation_mode`
- `spec_hash`
- `formula_hash`
- `code_hash`
- `data_catalog_hash`
- `data_api_contract_version`
- `window`
- `universe_hash`
- `frequency`
- selected factor parquet `sha256`
- selected factor parquet `row_count`
- selected factor parquet `schema`
- selected factor parquet key hash

Step4 now computes its expected formal identity and records a `factorforge_reuse_gate_v1` profile. Allowed decisions:

- `reuse_allowed`
- `recompute_required`
- `block_invalid_formal_reuse`

Smoke evidence from `/tmp/factorforge_performance_closeout_release_hygiene/performance_smoke_summary.json`:

| Case | Result |
| --- | --- |
| `step4_reuses_when_identity_matches` | `ok=true` |
| `step4_recomputes_when_code_hash_differs` | `ok=true` |
| `step4_recomputes_when_data_window_differs` | `ok=true` |
| `step4_recomputes_when_catalog_hash_differs` | `ok=true` |
| `step4_blocks_sample_proof_as_formal_factor_values` | `ok=true` |
| `step4_recomputes_when_cache_parquet_tampered` | `ok=true` |
| `performance_profile_script_readonly` | `ok=true` |

The tampered-cache case writes matching Step3B metadata, mutates the selected cache parquet bytes, and verifies Step4 rejects reuse with `reuse_gate.decision=recompute_required` before writing formal factor values.

`performance_profile_script_readonly` diagnostic codes included:

- `STEP3B_PERFORMANCE_PROFILE_PRESENT`
- `DEFAULT_NUMPY_TS_KERNELS_ENABLED`
- `STEP4_FACTOR_REUSE_PROFILE_PRESENT`
- `PARQUET_FORMAL_EVIDENCE_OK`
- `NORMALIZE_SORT_DOMINANT`
- `REUSE_GATE_ALLOWED`

## CSV/Parquet IO Evidence

Parquet remains formal evidence. CSV remains policy-controlled.

Smoke evidence:

- `csv_policy_sample_csv_parquet_formal_evidence`: PASS
- `csv_policy_no_csv_parquet_formal_evidence`: PASS
- `csv_policy_full_csv_legacy_compat`: PASS
- `step4_uses_parquet_when_full_csv_absent`: PASS
- `throughput_profile_reports_csv_policy`: PASS

Profiler diagnostic support:

- `PARQUET_FORMAL_EVIDENCE_OK`
- `FULL_CSV_ABSENT_BY_POLICY`
- `STEP4_RECOMPUTE_FALLBACK`
- `REUSE_GATE_ALLOWED`
- `REUSE_GATE_RECOMPUTE_REQUIRED`
- `REUSE_GATE_BLOCKED_INVALID_FORMAL_REUSE`

## Remaining Blocks

- `BLOCK_REAL_MAC_REPORT_NOT_PROVIDED`: no approved real report/run id was supplied.
- `BLOCK_EC2_WORKER_NOT_APPROVED_OR_UNAVAILABLE`: EC2 worker start was not authorized.

## Review Questions

1. Should the current baseline defaulting of `corr/cov` be retained, or should a separate rollback task move them back to opt-in despite current production constants?
2. Should a human-approved small real report/run id be supplied for Mac and EC2 performance proof, or is synthetic closeout acceptable for code review only?
