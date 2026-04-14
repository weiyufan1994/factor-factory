# Step 1 Core Prompts

## Primary Intake Prompt

Full prompt is embedded in SKILL.md. Key structural requirements:

- Output MUST be valid JSON only, no surrounding text
- Each subfactor needs: name, formula_or_expression, implementation_clues, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- Each final_factor needs: name, assembly_steps, component_subfactors, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- formula_clues, code_clues, implementation_clues extracted separately
- ambiguities field must list unresolved questions

## Challenger Intake Prompt

Same JSON structure as primary. Differences in instruction layer:
- "不要简单复述主路结论" — do not parrot primary
- "优先识别主路可能遗漏的..." — actively find gaps
- "若你不同意主路可能的最终因子选择，请明确给出不同的 final_factor" — challenge the final factor choice

## Chief Merge Prompt

Located at: `factorforge/skills/factor_forge_step1/prompts/step1_chief_merge.md`

Key decisions the chief must make:
1. Accept/reject each subfactor
2. Resolve logic_provenance disagreements (native vs inferred)
3. Determine final assembly_path
4. Assess alpha_strength (strong/medium/weak)
5. Flag unresolved_ambiguities with recommended_handling
6. Set chief_confidence (high/medium/low)

The chief must NOT:
- Accept logic as native if it was inferred
- Skip ambiguity resolution
- Issue vague decisions
