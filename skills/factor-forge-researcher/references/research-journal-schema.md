# Research Journal Schema

Path:

```text
factorforge/objects/research_journal/research_journal__<report_id>.json
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
- Each serious case should leave at least one transferable pattern, anti-pattern, or idea seed unless the evidence is too incomplete to support learning.
