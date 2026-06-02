# Step 1 Core Prompts

## Primary Intake Prompt

Full prompt is embedded in SKILL.md. Key structural requirements:

- Output MUST be valid JSON only, no surrounding text
- Each subfactor needs: name, formula_or_expression, implementation_clues, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- Each final_factor needs: name, assembly_steps, component_subfactors, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- formula_clues, code_clues, implementation_clues extracted separately
- ambiguities field must list unresolved questions
- economic_hypothesis_candidates must compare candidate return-source
  mechanisms rather than hard-coding one taxonomy
- preferred_economic_hypothesis must justify why it beats alternatives
- alternative_return_source_tests must include at least one discriminating test
- primary_mathematical_model must be selected from the economic hypothesis
- research_equation must classify the equation as strict_identity, institutional_constraint, behavioral_feedback, empirical_invariance, or research_conjecture, and must include assumptions, validity_scope, latent_state, observable_estimator, expected_metric_signature, falsification_tests, and kill_criteria
- t0_t1_stochastic_benchmark must explain whether the observable estimator affects drift, diffusion, jump, friction, regime transition, or observation equation over T+0/T+1 or report_horizon
- Do not default every factor to a stochastic process; stochastic process,
  Ito calculus, linear algebra, optimization, information theory, and causal
  tests are benchmark tools for projection, diagnostic, derivation, or
  falsification unless the report-specific hypothesis selects one as primary
- formula_as_observable_estimator must state the latent state, constraint,
  pressure, belief error, risk exposure, or information delay estimated by the
  formula and why this is not a raw-field restatement
- formula_implied_information, formula_implied_information_review, metric_signature_match by model layer, and drawdown geometry interpretation must be requested when Step4 metrics exist

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
7. Merge economic_hypothesis_candidates, preferred_economic_hypothesis,
   alternative_return_source_tests, primary_mathematical_model, and
   formula_as_observable_estimator without replacing unsupported gaps with a
   generic stochastic-process story

The chief must NOT:
- Accept logic as native if it was inferred
- Skip ambiguity resolution
- Issue vague decisions
