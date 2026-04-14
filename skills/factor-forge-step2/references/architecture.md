# Factor Forge Step 2 Architecture

## Purpose

Convert one `alpha_idea_master` into one canonical `factor_spec_master` for Step 3 implementation.

## Input Objects

- `factorforge/objects/alpha_idea_master/alpha_idea_master__{report_id}.json`
- `factorforge/objects/handoff/handoff__{report_id}.json` (optional path fallback)
- `factorforge/data/report_ingestion/report_registry.json`
- Step 1 upstream artifacts:
  - `factorforge/objects/validation/report_map_validation__{report_id}__alpha_thesis.json`
  - `factorforge/objects/validation/report_map_validation__{report_id}__challenger_alpha_thesis.json`
  - `factorforge/objects/report_maps/report_map__{report_id}__primary.json`

## Output Objects

- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step3__{report_id}.json`

## Flow

```text
alpha_idea_master
  ├─→ primary spec extraction
  ├─→ challenger spec extraction
  ├─→ consistency audit
  └─→ chief finalization (only if disagreement is material)
                    ↓
             factor_spec_master
                    ↓
              handoff_to_step3
```

## Current runner boundary

The bundled runner is now an independent Step 2 controller:
- it reads `alpha_idea_master`
- resolves the original PDF path
- reads Step 1 upstream thesis/report-map artifacts
- generates primary spec, challenger spec, consistency audit, canonical `factor_spec_master`, and `handoff_to_step3`

It no longer requires pre-existing Step 2 side artifacts for a fresh run.
