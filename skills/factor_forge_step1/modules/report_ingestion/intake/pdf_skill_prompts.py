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
        '  "evidence_clues": [{"clue": "", "location_hint": ""}],\\n'
        '  "ambiguities": [""]\\n'
        "}"
    )
