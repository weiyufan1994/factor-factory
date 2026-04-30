# Step3/4 Commenting Policy

This policy makes Step3/4 comments auditable and enforceable.

## Scope

- `skills/factor-forge-step3/scripts/run_step3.py`
- `skills/factor-forge-step3/scripts/run_step3b.py`
- `skills/factor-forge-step4/scripts/run_step4.py`
- `generated_code/{report_id}/factor_impl__{report_id}.py` or `generated_code/{report_id}/factor_impl_stub__{report_id}.py`

## Mandatory Rules

1. Core script markers
- `run_step3.py` and `run_step3b.py` must keep:
- `COMMENT_POLICY: runtime_path`
- `COMMENT_POLICY: execution_handoff`
- `run_step4.py` must keep:
- `COMMENT_POLICY: runtime_path`
- `COMMENT_POLICY: execution_handoff`
- `COMMENT_POLICY: backend_extensibility`

2. Factor implementation anchors
- The Step3/4 implementation file selected for a report must contain:
- `# CONTEXT:`
- `# CONTRACT:`
- `# RISK:`

3. Comment quality
- Comments must explain intent, assumptions, interfaces, or failure boundaries.
- Do not add noise comments that only restate obvious syntax.

## Enforcement

- Manual check:
- `python3 scripts/check_step34_comment_policy.py --report-id <report_id>`
- Pipeline gate:
- `./scripts/run_pipeline_with_agent_handoff.sh mark-step34-done`
- `./scripts/run_pipeline_with_agent_handoff.sh resume`

Both pipeline commands run the same comment-policy check. If it fails, Step5 is blocked.
