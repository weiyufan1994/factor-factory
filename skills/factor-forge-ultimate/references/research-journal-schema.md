# Research journal field guide

This is the existing journal shape, not an instruction to prefill successful
reviews. Before a stage is complete, retain unknowns and unfinished sections;
booleans below illustrate field types, not observed results. Paths are relative
to the declared factor workspace. Empty learning collections need an explicit
reason under the study's content rules. Mechanism changes return to Step2 even
though the legacy revision field is named `step3b_changes_requested`.

Path:

```text
objects/research_journal/research_journal__<report_id>.json
```

Required shape:

```json
{
  "report_id": "string",
  "factor_id": "string",
  "source_understanding": {
    "source_type": "paper|sell_side_report|manual_idea|known_formula|other",
    "author_thesis": "string",
    "researcher_interpretation": "string",
    "expected_return_source": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed|unknown",
    "what_must_be_true": ["string"],
    "what_would_break_it": ["string"]
  },
  "canonical_spec_review": {
    "formula_plain_language": "string",
    "inputs_required": ["string"],
    "implementation_invariants": ["string"],
    "open_questions_before_step3": ["string"]
  },
  "implementation_review": {
    "data_contract_ok": true,
    "code_matches_formula": true,
    "known_approximations": ["string"],
    "implementation_risks": ["string"]
  },
  "evidence_review": {
    "positive_evidence": ["string"],
    "negative_evidence": ["string"],
    "ambiguities": ["string"],
    "chart_observations": ["string"],
    "tradability_assessment": "string"
  },
  "reflection": {
    "current_decision": "promote_official|iterate|reject|needs_human_review|not_ready",
    "decision_rationale": ["string"],
    "knowledge_to_keep": ["string"],
    "failure_lessons": ["string"],
    "success_lessons": ["string"],
    "transferable_patterns": ["string"],
    "anti_patterns": ["string"],
    "innovative_idea_seeds": ["string"]
  },
  "revision_history": [
    {
      "iteration_no": 0,
      "reason": "string",
      "step3b_changes_requested": ["string"],
      "expected_improvement": ["string"],
      "kill_criteria": ["string"]
    }
  ],
  "created_at_utc": "string",
  "updated_at_utc": "string",
  "producer": "factor-forge-researcher"
}
```

Quality bar:

- The journal should make a future agent better, not merely describe file status.
- If the factor fails, the journal must explain what was learned and why the failure matters.
- If the factor iterates, the revision must tie back to a return-source thesis.
- Record supported lessons or a concrete reason no transferable insight was found.

## Optional local implementation-review continuation

`code_review_coordination` holds the active request and prior requests inside
this same journal: author/reviewer, exact material versions, actual tool-call
outcomes, findings, test/command failures and a scoped resume point. Existing
research content above is preserved. Ultimate is the single journal writer;
the independent reviewer writes a separate result which Ultimate consumes.

The input/actions and limits are defined once in
[Ultimate's local code-review reference](local-code-review.md).
This field is operational continuity, not proof of agent independence, research
validity, delivery or promotion. A prepared record alone does not mean a task
was sent. It never enables knowledge writeback or changes the study's scope.
