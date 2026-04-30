from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z_]{3,}|[\u4e00-\u9fff]{1,}", text.lower()))


def _text_blob(*objects: Any) -> str:
    return " ".join(_stringify(obj) for obj in objects).lower()


def infer_step1_random_object(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["成交量", "换手", "volume", "turnover", "amount", "order", "flow"]):
        return "A-share liquidity/order-flow and price panel observed through tradable market data"
    if any(tok in text for tok in ["close", "open", "high", "low", "return", "收益", "价格", "价量", "影线"]):
        return "A-share daily/intraday price-return panel and cross-sectional return ordering"
    if any(tok in text for tok in ["revenue", "profit", "cash", "contract", "inventory", "liability", "营收", "利润", "现金流", "合同负债", "存货"]):
        return "firm fundamental information state observed through accounting and disclosure fields"
    if any(tok in text for tok in ["北交所", "转板", "公募", "保险", "mandate", "index", "rebalance"]):
        return "security panel affected by objective market-structure or mandate constraints"
    return "report-defined security panel; researcher must restate the precise random object before promotion"


def infer_target_statistic_hint(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["rank", "排名", "分组", "quantile", "bucket"]):
        return "cross-sectional ordering / rank statistic for future returns"
    if any(tok in text for tok in ["corr", "相关", "cov"]):
        return "rolling dependence statistic used to predict cross-sectional return ordering"
    if any(tok in text for tok in ["std", "vol", "波动", "方差"]):
        return "conditional dispersion / volatility statistic linked to future returns"
    if any(tok in text for tok in ["skew", "偏度", "tail", "尾部"]):
        return "higher-moment or tail-shape statistic linked to future returns"
    return "conditional expected return or cross-sectional ranking effect inferred from the report thesis"


def infer_return_source_hypothesis(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["value", "size", "beta", "quality", "价值", "规模", "风险补偿", "低波"]):
        return "risk_premium"
    if any(tok in text for tok in ["财报", "基本面", "合同负债", "现金流", "revenue", "profit", "cash", "information", "disclosure"]):
        return "information_advantage"
    if any(tok in text for tok in ["北交所", "转板", "公募", "保险", "约束", "制度", "mandate", "rebalance", "liquidity", "流动性"]):
        return "constraint_driven_arbitrage"
    if any(tok in text for tok in ["momentum", "reversal", "过度反应", "反转", "动量", "行为"]):
        return "mixed"
    return "mixed"


def infer_information_set_hint(alpha_idea_master: Dict[str, Any], *context: Any) -> str:
    text = _text_blob(alpha_idea_master, *context)
    if any(tok in text for tok in ["future", "lead", "lookahead", "未来收益", "事后"]):
        return "possible_forward_reference_requires_human_review"
    if any(tok in text for tok in ["lag", "shift", "delay", "滞后", "前一日"]):
        return "explicit_lag_or_delay_documented"
    return "requires_researcher_confirmation_no_forward_leakage"


def load_similar_case_lessons(repo_root: Path, query_text: str, top_k: int = 3) -> List[str]:
    candidates: List[tuple[float, str]] = []
    q_tokens = _tokens(query_text)
    index_paths = [
        repo_root / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
        repo_root / "factorforge" / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
    ]
    for path in index_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue
            text = _stringify(doc.get("text") or doc)
            overlap = len(q_tokens & _tokens(text))
            if overlap <= 0:
                continue
            label = " / ".join(str(x) for x in [doc.get("factor_id"), doc.get("decision")] if x)
            candidates.append((float(overlap), (label + ": " + text[:300]).strip(": ")))
    candidates.sort(key=lambda item: item[0], reverse=True)
    lessons = []
    seen = set()
    for _, item in candidates:
        if item and item not in seen:
            lessons.append(item)
            seen.add(item)
        if len(lessons) >= top_k:
            break
    if not lessons:
        lessons.append("No similar prior case was retrieved at Step1; treat this as a cold-start prior and write back lessons after Step6.")
    return lessons


def build_step1_research_discipline(
    alpha_idea_master: Dict[str, Any],
    repo_root: Path | None = None,
    *context: Any,
) -> Dict[str, Any]:
    repo = repo_root or Path.cwd()
    final_factor = alpha_idea_master.get("final_factor") or {}
    query_text = _text_blob(alpha_idea_master.get("report_id"), final_factor.get("name"), final_factor, alpha_idea_master.get("assembly_path"), *context)
    random_object = infer_step1_random_object(alpha_idea_master, *context)
    target_hint = infer_target_statistic_hint(alpha_idea_master, *context)
    return_source = infer_return_source_hypothesis(alpha_idea_master, *context)
    info_hint = infer_information_set_hint(alpha_idea_master, *context)
    similar_lessons = load_similar_case_lessons(repo, query_text)
    what_must_be_true = _as_list(final_factor.get("what_must_be_true")) or _as_list(final_factor.get("economic_logic"))[:1]
    what_would_break_it = _as_list(final_factor.get("what_would_break_it")) or _as_list(final_factor.get("key_implementation_risks"))
    if not what_must_be_true:
        what_must_be_true = ["The report thesis must map to a repeatable return source rather than one-off descriptive pattern fitting."]
    if not what_would_break_it:
        what_would_break_it = ["The thesis breaks if the signal cannot survive legal information-set review, robustness checks, or tradable portfolio construction."]
    return {
        "step1_random_object": random_object,
        "target_statistic_hint": target_hint,
        "information_set_hint": info_hint,
        "initial_return_source_hypothesis": return_source,
        "what_must_be_true": [str(x) for x in what_must_be_true if str(x).strip()],
        "what_would_break_it": [str(x) for x in what_would_break_it if str(x).strip()],
        "similar_case_lessons_imported": similar_lessons,
        "producer": "step1_research_discipline",
    }


def attach_step1_research_discipline(
    alpha_idea_master: Dict[str, Any],
    repo_root: Path | None = None,
    *context: Any,
) -> Dict[str, Any]:
    out = dict(alpha_idea_master)
    discipline = build_step1_research_discipline(out, repo_root, *context)
    out["research_discipline"] = {
        **(out.get("research_discipline") or {}),
        **discipline,
    }
    out.setdefault("step1_random_object", discipline["step1_random_object"])
    math_review = dict(out.get("math_discipline_review") or {})
    math_review.setdefault("step1_random_object", discipline["step1_random_object"])
    math_review.setdefault("target_statistic", discipline["target_statistic_hint"])
    math_review.setdefault("information_set_legality", discipline["information_set_hint"])
    out["math_discipline_review"] = math_review
    learning = dict(out.get("learning_and_innovation") or {})
    learning.setdefault("similar_case_lessons_imported", discipline["similar_case_lessons_imported"])
    out["learning_and_innovation"] = learning
    return out
