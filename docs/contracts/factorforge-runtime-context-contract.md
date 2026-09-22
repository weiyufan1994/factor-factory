# Factor Forge Runtime Context Contract v1

## Goal

All Step / Skill / Worker code should resolve paths through one standard runtime context instead of repeatedly guessing:

- `FACTORFORGE_ROOT`;
- EC2 legacy workspace;
- `objects/`;
- `runs/`;
- `evaluations/`;
- handoff / factor values / branch result filenames.

This contract does not replace Step1-6 business objects. It provides the shared artifact map.

## Standard Python Interface

```python
from factor_factory.runtime_context import resolve_factorforge_context

ctx = resolve_factorforge_context()

ctx.factorforge_root
ctx.objects_root
ctx.runs_root
ctx.evaluations_root
ctx.archive_root
ctx.clean_data_root

ctx.object_path('handoff_to_step4', report_id)
ctx.object_path('factor_evaluation', report_id)
ctx.factor_values_path(report_id, 'parquet')
ctx.step3a_daily_input_path(report_id)
ctx.evaluation_payload_path(report_id, 'self_quant_analyzer')
ctx.search_branch_result_path(report_id, branch_id)
ctx.remap_legacy_path(raw_path)
```

## Manifest

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

Writes:

```text
factorforge/objects/runtime_context/runtime_context__<report_id>.json
```

Branch context:

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --branch-id <branch_id> --write
```

Writes:

```text
factorforge/objects/runtime_context/runtime_context__<report_id>__<branch_id>.json
```

The manifest now has four layers:

- `objects`: canonical object artifact paths, such as `factor_spec_master`, `handoff_to_step4`, and `factor_case_master`.
- `runs`: run-level artifact paths, such as `factor_values_parquet`, `step3a_daily_input_csv`, and `run_metadata`.
- `evaluations`: Step4 backend payload paths, such as `self_quant_payload` and `qlib_backtest_payload`.
- `step_io`: explicit Step3/4/5/6 input and output maps.

## Step I/O Boundary

Starting from v1.1:

- the skill / agent / top-level orchestrator discovers inputs, fixes outputs, and writes the manifest;
- step scripts consume explicit manifest paths;
- `--report-id` remains a backward-compatible fallback only;
- when a manifest field exists, scripts must not enumerate ad-hoc candidate directories or silently use old files;
- backend workers inherit the same manifest / `FACTORFORGE_ROOT`.

Recommended execution:

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
python3 skills/factor-forge-step3/scripts/run_step3.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step3/scripts/run_step3b.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step4/scripts/run_step4.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step5/scripts/run_step5.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step6/scripts/run_step6.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
```

## Resolution Rules

1. Prefer explicit `FACTORFORGE_ROOT`.
2. On EC2, use `/home/ubuntu/.openclaw/workspace/factorforge` when it exists.
3. Otherwise use the repo root as local runtime root.
4. Handoffs may contain relative paths, but consumers must resolve them via `ctx.remap_legacy_path()`.
5. Legacy EC2 absolute paths may be remapped to the active `factorforge_root`.
6. If a manifest field exists, workers should not enumerate ad-hoc candidate directories.

## JSON Writes

New workers should use:

```python
from factor_factory.runtime_context import write_json_atomic, update_json_locked
```

Shared ledgers must use locked update. Do not use bare `load -> modify -> write` on shared ledgers.
