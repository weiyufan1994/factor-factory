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

The runner consumes approved upstream inputs and materializes the spec/audit/
handoff through Ultimate. It is not evidence that two independent agents ran.
For local PDF studies, Step1 references actual agent-authored primary/challenger
raw specs and an adjudicated canonical core; missing/conflicting inputs block
rather than generating a generic correlation template. See
[local-pdf-inputs.md](local-pdf-inputs.md). Non-PDF source adapters retain their
own contracts and do not need an invented PDF. Agent invocation and substantive
adjudication remain researcher responsibilities.
