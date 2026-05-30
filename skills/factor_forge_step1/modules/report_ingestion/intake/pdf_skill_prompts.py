from __future__ import annotations


def build_step1_report_intake_prompt() -> str:
    return (
        "请阅读这篇研报，并严格按以下 JSON 结构输出，不要输出 JSON 以外的任何文字。\\n"
        "要求：\\n"
        "1. 把因子尽量拆到最小可拆分子因子；\\n"
        "2. 对每个子因子和最终合成因子，都分别给出 economic_logic、behavioral_logic、causal_chain；\\n"
        "3. 每条 logic 都要标明 source 是 native 还是 inferred；如果是根据表达式/公式推断，必须明确写 inferred；\\n"
        "4. 把报告中的公式、表达式、伪代码、实现线索尽量单列抽出；\\n"
        "5. 若报告未明确解释逻辑，可根据表达式做谨慎推断，但必须标注 inferred。\\n"
        "6. economic_hypothesis 不是公式复述，也不是故事。它必须解释：在信息集 F_t 下，"
        "为什么该信号会改变未来收益的条件分布。\\n"
        "7. 把收益来源分类为候选集合，而不是唯一答案：risk_premium、information_advantage_or_delayed_diffusion、"
        "liquidity_or_price_pressure、institutional_or_constraint_rent、time_option、"
        "behavioral_or_organizational_bias、market_microstructure、fundamental_repricing、"
        "statistical_or_measurement_artifact、mixed_or_other。\\n"
        "8. 对每个候选 economic_hypothesis_candidates 写明 payer_or_counterparty（若无明确对手方可为 null）、"
        "why_counterparty_cannot_stop、risk_borne_by_us、market_structure_or_constraint、observable_state、"
        "how_signal_changes_return_distribution、required_assumptions、what_would_break_it、report_support、confidence。\\n"
        "9. 必须给出 preferred_economic_hypothesis，并至少给出一个 alternative_return_source_tests；"
        "替代解释可以是 risk premium、信息扩散、流动性冲击、制度约束、行为偏误、基本面重定价或统计伪影。\\n"
        "10. 必须给出 primary_mathematical_model：由经济假设选择主数学建模工具，"
        "例如 asset pricing、Bayesian updating、signal extraction、price impact、inventory model、"
        "constrained optimization、attention/overreaction model、regime switching、valuation decomposition、"
        "causal/placebo framework 等。\\n"
        "11. Do not default every factor to a stochastic process. Stochastic process, Ito calculus, "
        "linear algebra, optimization, information theory, and causal tests are benchmark tools used for "
        "projection, diagnostic, derivation, or falsification; they are not automatically the primary model.\\n"
        "12. 公式是 observable estimator：说明它估计的 latent state、constraint、pressure、belief error、risk exposure "
        "或 information delay；禁止只把公式字段换一种说法。\\n"
        "JSON 结构：\\n"
        "{\\n"
        '  "report_meta": {"title": "", "broker": "", "topic": ""},\\n'
        '  "section_map": [{"section_title": "", "summary": ""}],\\n'
        '  "variables": [""],\\n'
        '  "signals": [""],\\n'
        '  "subfactors": [{"name": "", "formula_or_expression": "", "implementation_clues": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]}],\\n'
        '  "final_factor": {"name": "", "assembly_steps": [""], "component_subfactors": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]},\\n'
        '  "formula_clues": [{"content": "", "location_hint": ""}],\\n'
        '  "code_clues": [{"content": "", "location_hint": ""}],\\n'
        '  "implementation_clues": [{"content": "", "location_hint": ""}],\\n'
        '  "alpha_candidates": [{"name": "", "logic": "", "direction": ""}],\\n'
        '  "economic_hypothesis_candidates": [{"candidate_id": "", "return_source_family": "", "mechanism_summary": "", "payer_or_counterparty": null, "why_counterparty_cannot_stop": null, "risk_borne_by_us": "", "market_structure_or_constraint": "", "time_horizon": "", "observable_state": "", "how_signal_changes_return_distribution": "", "required_assumptions": [""], "what_would_break_it": [""], "report_support": {"native_claims": [""], "inferred_links": [""], "unsupported_gaps": [""]}, "confidence": "high|medium|low"}],\\n'
        '  "preferred_economic_hypothesis": {"candidate_id": "", "why_preferred_over_alternatives": ""},\\n'
        '  "alternative_return_source_tests": [{"alternative_source": "", "why_not_primary": "", "discriminating_test": "", "expected_signature_if_alternative_true": "", "expected_signature_if_preferred_true": ""}],\\n'
        '  "primary_mathematical_model": {"model_family": "", "why_selected_from_economic_hypothesis": "", "core_state_variables": [""], "benchmark_math_tools": [""], "stochastic_return_projection_role": "projection|diagnostic|derivation|falsification|not_primary"},\\n'
        '  "formula_as_observable_estimator": {"latent_state_or_constraint": "", "estimator_interpretation": "", "why_not_raw_field_restatement": "", "expected_metric_signature": [""], "falsification_tests": [""]},\\n'
        '  "evidence_clues": [{"clue": "", "location_hint": ""}],\\n'
        '  "ambiguities": [""]\\n'
        "}"
    )
