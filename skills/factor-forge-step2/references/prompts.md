# Step 2 Prompt Pack

## Primary Route

Use the PDF plus `alpha_idea_master` to recover the construction spec faithfully.

Focus on:
- formula text
- required inputs
- operators
- time-series steps
- cross-sectional steps
- preprocessing
- normalization
- neutralization
- rebalance frequency
- explicit ambiguities

## Challenger Route

Read adversarially. Try to find what the primary route flattened, skipped, or over-assumed.

Focus on:
- alternative formula interpretations
- missing operator steps
- hidden assumptions
- places where `alpha_idea_master` may overstate certainty

## Consistency Audit

Judge whether primary + challenger remain faithful to the alpha thesis.

Return:
- consistency_score
- mismatch_points
- missing_steps
- distortion_risks
- recommendation (`proceed|revise|stop`)

## Chief Finalization Trigger

Escalate only when:
- `consistency_score < 0.7`, or
- primary vs challenger have more than two material disagreements on inputs/operators/reconstruction logic.

Otherwise keep `opus_invoked = false` and use primary + consistency to finalize the canonical spec.
