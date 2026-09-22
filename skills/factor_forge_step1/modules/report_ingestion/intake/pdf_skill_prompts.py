from __future__ import annotations

import json

from factor_factory.measurement_program import measurement_program_template


def build_step1_report_intake_prompt() -> str:
    measurement_program_schema = measurement_program_template(
        placeholder="<mechanism-specific agent-authored value>",
        implementation_route="operator",
    )
    measurement_program_schema["implementation"]["route"] = (
        "operator|direct_code|hybrid"
    )
    measurement_program_schema["implementation"]["web_execution_status"] = (
        "trusted_formula_ir_execution|model_only_requires_trusted_isolated_code_harness"
    )
    measurement_program_json = json.dumps(
        measurement_program_schema,
        ensure_ascii=False,
        indent=2,
    )
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
        "10. 必须先做开放的 math_tool_selection，再由经济假设选择 primary_mathematical_model。"
        "候选可包括 DCF、剩余收益、会计恒等式、asset pricing、Bayesian updating、signal extraction、"
        "price impact、inventory model、stochastic process、constrained optimization、信息论、"
        "泛函/谱/信号处理、因果、图或其他新组合对象；不得由已有算子或数据便利性决定。\\n"
        "11. Do not default every factor to a stochastic process or dimensional analysis. "
        "Specialized audits are selected only when the chosen mechanism makes them relevant; an empty "
        "specialized-audit list is valid when the core derivation, observation map and falsifiers are complete.\\n"
        "12. 公式或代码是 observation/estimation map：说明它测量的数学对象，例如 intrinsic value、accounting identity、"
        "constraint、pressure、belief error、risk exposure、signal component 或仅在机制确需时的 latent state；"
        "禁止只把字段或算子换一种说法。\\n"
        "13. 必须完整填写 mechanism_conditioned_measurement_program。每个 primary、mechanism_alternative、null_alias "
        "候选模型都要分别写 mathematical_object、mechanism_equation_or_functional、target_functional、"
        "market_outcome_projection 和 observation_mapping；核心机制方程不得复用市场结果投影。"
        "primary/challenger 必须独立作答，若不一致由 chief 明确选择或重建，不得由 Python 猜测。\\n"
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
        '  "primary_mathematical_model": {"model_family": "", "why_selected_from_economic_hypothesis": "", "core_mathematical_objects": [""], "candidate_tool_families": [""], "selected_tool_families": [""], "rejected_tool_families": [{"tool_family": "", "reason": ""}], "applicable_specialized_audits": []},\\n'
        '  "formula_as_observable_estimator": {"latent_state_or_constraint": "", "estimator_interpretation": "", "why_not_raw_field_restatement": "", "expected_metric_signature": [""], "falsification_tests": [""]},\\n'
        '  "mechanism_conditioned_measurement_program": '
        + measurement_program_json
        + ',\\n'
        '  "evidence_clues": [{"clue": "", "location_hint": ""}],\\n'
        '  "ambiguities": [""]\\n'
        "}"
    )
