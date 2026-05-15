---
report_id: "ALPHA009_ALPHA007_CHOPPY_SKEW_20260422"
factor_id: "Alpha007Extended"
decision: "iterate"
tags:
  - "knowledge"
  - "iterate"
---

# Knowledge Record: Alpha007Extended (ALPHA009_ALPHA007_CHOPPY_SKEW_20260422)

- decision: `iterate`

## Framework
- `factor_family`: `None`
- `monetization_model`: `None`
- `bias_type`: `None`
- `objective_constraint_dependency`: `None`
- `crowding_risk`: `None`
- `capacity_constraints`: `None`
- `implementation_risk`: `None`

## Return Source Hypothesis
- (none)

## Constraint Sources
- (none)

## Success Patterns
- (none)

## Failure Patterns
- (none)

## Expected Failure Regimes
- Data with fewer than 60 trading days for skew estimation
- Markets where choppy/trend detection frequency differs significantly from 2010-2026 A-share patterns

## Modification Hypotheses
- (none)

## Improvement Frontier
- Verify with 200+ day OOS when data is refreshed to current date
- Test finer alpha grid (0.1, 0.15, 0.2)
- Test bidirectional signal (long inv_chop, short norm_chop)
- Investigate economic mechanism of inv_chop (noise suppression vs crowding)

## Review Checklist
- (none)

## Revision Principles
- (none)

## DD · View · Edge · Trade
- (none)

## Research Commentary
- (none)

## Links

- (none)
