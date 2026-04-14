# Factor Forge Step 1 Architecture

## Module Map

```
modules/report_ingestion/
├── intake/
│   ├── pdf_skill_client.py      ← parses pdf skill JSON → StructuredIntake
│   ├── pdf_skill_prompts.py     ← primary/challenger prompt builders
│   └── structured_intake_contract.py  ← dataclass for intake
├── normalizers/
│   ├── intake_to_report_map.py
│   ├── intake_to_alpha_thesis.py
│   └── intake_to_ambiguity_review.py
├── challenger/
│   ├── challenger_prompt.py
│   ├── challenger_runner.py
│   └── challenger_to_thesis.py
├── diff/
│   ├── intake_diff.py           ← compares primary vs challenger intake
│   └── thesis_diff.py           ← compares primary vs challenger thesis
├── merge/
│   ├── chief_merge_client.py    ← builds merge prompt, calls pdf skill
│   └── merge_to_alpha_idea_master.py
├── finalizers/
│   ├── alpha_idea_master_writer.py
│   └── handoff_to_step2.py
├── orchestration/
│   └── step1_pipeline.py       ← main pipeline orchestrator
├── registry/
│   ├── report_registry.py       ← tracks all ingested reports
│   └── report_source_contract.py
└── writers/
    └── object_writer.py         ← writes all output JSON files
```

## Data Flow

```
PDF
  ├─→ pdf_skill (primary prompt) → primary_raw.json
  │                                    ↓
  │                              primary_intake
  │                                    ↓
  │                    ┌─────────────────────────────┐
  │                    ↓              ↓               ↓
  │              report_map    alpha_thesis    ambiguity_review
  │                    └─────────────────────────────┘
  │
  └─→ pdf_skill (challenger prompt) → challenger_raw.json
                                       ↓
                                 challenger_intake
                                       ↓
                         ┌─────────────────────────────┐
                         ↓              ↓               ↓
                   report_map    challenger_thesis  (derived)
                         └─────────────────────────────┘
                                       ↓
                              intake_diff + thesis_diff
                                       ↓
                                  chief_merge
                                    (pdf skill)
                                       ↓
                              alpha_idea_master
                                       ↓
                    ┌──────────────────────────────┐
                    ↓                              ↓
           alpha_idea_master.json          handoff.json
```

## Object Schemas Summary

### StructuredIntake (primary_intake, challenger_intake)
- report_meta, section_map, variables, signals
- subfactors[] — atomic factors with formula/logic/causal_chain
- final_factor — assembled factor with assembly_steps
- formula_clues[], code_clues[], implementation_clues[]
- ambiguities[]

### AlphaThesis
- thesis_name, economic_logic, behavioral_logic, causal_chain
- Each logic field has a `_source` field: "native" or "inferred"
- subfactors[], final_factor, direction

### alpha_idea_master
- Canonical output combining both routes
- accepted_subfactors, rejected_subfactors
- assembly_path (executable steps)
- logic_provenance_summary
- unresolved_ambiguities with recommended_handling
- chief_confidence, chief_rationale
