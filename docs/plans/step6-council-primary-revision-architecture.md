# Step6 Council-Primary Revision Architecture

## Goal

Upgrade Revision Council from a manually triggered advisory scaffold into the primary revision research engine for Step6, while preserving Step6 Core as the evidence gatekeeper, safety controller, and deterministic fallback.

Target split:

```text
Step6 Core = evidence gate / safety controller / deterministic fallback
Revision Council = primary revision research engine
```

This is not a Step7. Council remains a Step6 extension.

## Current State

Step6 currently generates deterministic revision artifacts directly from evidence and predefined failure signatures:

```text
evidence_audit
mechanism_analysis
case_comparison
revision_strategy
search_policy_decision
loop_research_brief
optional handoff_to_step3b
```

The deterministic strategy is useful for safety and fallback, but it is not the desired agentic research layer. Revision Council already provides packet/proposal/merge artifacts, derivation records, symbolic law discovery, dimensional review, and no-writeback baseline guards, but it is still manually triggered and not attached back into the Step6 final revision decision.

## Target Architecture

```text
Step1 -> Step2 -> Step3 -> Step4 -> Step5 -> Step6
                                      |
                                      |-- Step6 Core
                                      |     - evidence audit
                                      |     - mechanism analysis
                                      |     - case comparison
                                      |     - deterministic revision fallback
                                      |     - prewrite gate
                                      |     - promotion / reject / iterate
                                      |     - loop research brief
                                      |
                                      |-- Step6 Revision Council
                                      |     - packet
                                      |     - proposals
                                      |     - derivation records
                                      |     - council merge
                                      |     - council revision strategy
                                      |
                                      |-- Step6 Final Revision Decision
                                            - source = revision_council | deterministic_fallback | none
                                            - human approval gate
                                            - optional Step3B handoff
```

## Principles

1. Council is the primary revision engine when revision is needed.
2. Step6 Core remains the only safety controller.
3. Council must not directly write Step3B handoff, generated code, official library, or clean data.
4. Council output is advisory-only by default.
5. Step6 deterministic revision strategy remains available as fallback.
6. All public reasoning must be recorded through derivation artifacts; no hidden chain-of-thought is required or stored.
7. Final Step3B handoff still requires Step6 authorization and human approval.

## Council Trigger Policy

Council should be triggered when any of these are true:

```text
decision = iterate
revision_strategy.revision_needed = true
mechanism_fit in {weak, contradicted}
primary_failure_signature not in {none}
```

Council should not run when:

```text
decision = promote_official and revision_needed=false
evidence_audit.evidence_verdict=blocked
case_comparison_verdict=blocked
implementation_suspect before audit repair
```

## Step6 Iteration Additions

Add `revision_council_ref` to `research_iteration_master__<report_id>.json`:

```json
{
  "enabled": true,
  "mode": "scaffold",
  "status": "completed",
  "packet_path": "objects/research_iteration_master/revision_council/<report_id>/revision_council_packet__<report_id>.json",
  "summary_path": "objects/research_iteration_master/revision_council/<report_id>/revision_council_summary__<report_id>.json",
  "proposal_count": 7,
  "valid_proposal_count": 7,
  "blocked_proposal_count": 0,
  "recommended_branch_count": 2,
  "producer_modes": ["deterministic_scaffold"],
  "research_depths": ["low"],
  "canonical_write_permission": false,
  "human_approval_required": true
}
```

If not triggered:

```json
{
  "enabled": false,
  "status": "not_triggered",
  "reason": "no_revision_needed"
}
```

If blocked:

```json
{
  "enabled": true,
  "status": "blocked",
  "block_reason": "BLOCK_REVISION_COUNCIL_..."
}
```

## Research Memo Additions

Add these fields under `research_memo`:

```json
{
  "deterministic_revision_strategy": {},
  "council_revision_strategy": {},
  "final_revision_strategy": {
    "source": "revision_council",
    "fallback_used": false,
    "revision_needed": true,
    "primary_failure_signature": "cost_too_high",
    "revision_hypotheses": [],
    "loop_authorization": "advisory_only",
    "approval_required_before_step3b": true,
    "selected_council_proposal_ids": [],
    "why_selected": "Council produced valid derivation-backed proposals.",
    "why_deterministic_fallback_not_used": "Council output was valid."
  }
}
```

If Council is unavailable or invalid under an allowed fallback mode:

```json
{
  "source": "deterministic_fallback",
  "fallback_used": true,
  "fallback_reason": "revision_council_failed_or_not_available"
}
```

## Council Summary Requirements

`revision_council_summary__<report_id>.json` should expose enough structure for Step6 to attach it:

```json
{
  "summary_version": "factorforge_revision_council_summary_v1",
  "report_id": "...",
  "status": "completed",
  "proposal_count": 7,
  "valid_proposals": [],
  "blocked_proposals": [],
  "recommended_branches": [],
  "selected_revision_hypotheses": [],
  "derivation_record_refs": [],
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval_required": true
}
```

## Final Revision Strategy Selection

Selection rule:

```text
if council summary is valid and selected revision hypotheses exist:
    final_revision_strategy.source = revision_council
else:
    final_revision_strategy.source = deterministic_fallback
```

Mandatory blocks:

```text
canonical_write_permission=true
execution_allowed_by_default=true
selected proposal missing derivation_record
selected proposal contains forbidden portfolio/short/decile/clean-data repair
handoff_to_step3b exists without approved final revision strategy
```

## Step3B Handoff Policy

Council cannot write `objects/handoff/handoff_to_step3b__<report_id>.json`.

Step6 Core may write it only when:

```text
decision == iterate
final_revision_strategy.revision_quality == actionable
final_revision_strategy.loop_authorization == approved_for_step3b_handoff
case_comparison_verdict != blocked
similar_success_condition_mismatch != true
human approval exists
```

Without approval:

```text
loop_authorization = advisory_only
handoff_to_step3b absent
```

## Recommended Implementation Phases

### Phase J.1: Council Attachment

Implement Council attachment after Step6 and Council already ran:

```text
Step6 already run
Council packet/proposals/summary already exist
attach council summary back to Step6 iteration
validate Step6 council-primary fields
```

No ultimate wrapper integration yet.

### Phase J.2: Ultimate Integration

Add optional wrapper mode:

```bash
--council-mode off|auto|scaffold|agentic
```

Recommended behavior:

```text
off: Step6 only
auto: run Council only when revision is needed
scaffold: force scaffold Council when Step6 is not blocked
agentic: future mode; block if not implemented
```

## Non-goals

Do not implement in Phase J.1:

```text
real multi-agent execution
automatic Step3B code modification
direct generated_code patching
automatic search worker execution
Step7
default official promotion from Council
```

## Intended End State

```text
Step6 Core:
  deterministic, safe, evidence-aware, fallback revision

Revision Council:
  primary revision engine, derivation-backed, advisory-only by default

Ultimate:
  can later run Step6 + Council through explicit council mode

Step3B:
  only receives handoff after explicit approval
```
