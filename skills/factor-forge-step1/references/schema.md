# Step 1 Data Schemas

## StructuredIntake

```python
@dataclass
class SubFactor:
    name: str
    formula_or_expression: str
    implementation_clues: List[str]
    economic_logic: str
    economic_logic_source: Literal["native", "inferred"]
    behavioral_logic: str
    behavioral_logic_source: Literal["native", "inferred"]
    causal_chain: str
    causal_chain_source: Literal["native", "inferred"]
    ambiguities: List[str]

@dataclass
class FinalFactor:
    name: str
    assembly_steps: List[str]
    component_subfactors: List[str]
    economic_logic: str
    economic_logic_source: str
    behavioral_logic: str
    behavioral_logic_source: str
    causal_chain: str
    causal_chain_source: str
    ambiguities: List[str]

@dataclass
class StructuredIntake:
    report_id: str
    report_meta: dict  # {title, broker, topic}
    section_map: List[dict]  # [{section_title, summary}]
    variables: List[str]
    signals: List[str]
    subfactors: List[SubFactor]
    final_factor: FinalFactor
    formula_clues: List[dict]  # [{content, location_hint}]
    code_clues: List[dict]
    implementation_clues: List[dict]
    alpha_candidates: List[dict]  # [{name, logic, direction}]
    evidence_clues: List[dict]  # [{clue, location_hint}]
    ambiguities: List[str]
    raw_response: str
```

## alpha_idea_master

```json
{
  "report_id": "string",
  "chief_decision_summary": "string",
  "final_factor": {
    "name": "string",
    "assembly_steps": ["string"],
    "accepted_subfactor_names": ["string"],
    "rejected_subfactor_details": [{"name": "string", "reason": "string"}],
    "economic_logic": "string",
    "economic_logic_provenance": "native|inferred",
    "behavioral_logic": "string",
    "behavioral_logic_provenance": "native|inferred",
    "causal_chain": "string",
    "causal_chain_provenance": "native|inferred",
    "direction": "string",
    "alpha_strength": "strong|medium|weak",
    "alpha_source": "string",
    "key_implementation_risks": ["string"]
  },
  "logic_provenance_summary": {
    "native_logic_items": ["string"],
    "inferred_logic_items": ["string"],
    "provenance_disagreements_resolved": ["string"]
  },
  "assembly_path": ["string"],
  "unresolved_ambiguities": [
    {"ambiguity": "string", "recommended_handling": "string"}
  ],
  "chief_confidence": "high|medium|low",
  "chief_rationale": "string"
}
```

## Intake Diff

```json
{
  "primary_final_factor": "string",
  "challenger_final_factor": "string",
  "primary_subfactors": ["string"],
  "challenger_subfactors": ["string"],
  "ambiguity_gap": {
    "primary": ["string"],
    "challenger": ["string"]
  }
}
```

## Thesis Diff

```json
{
  "economic_logic": {"primary": "string", "challenger": "string"},
  "behavioral_logic": {"primary": "string", "challenger": "string"},
  "causal_chain": {"primary": "string", "challenger": "string"},
  "logic_sources": {
    "economic_logic_source": {"primary": "native|inferred", "challenger": "native|inferred"}
  }
}
```
