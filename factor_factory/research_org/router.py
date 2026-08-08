from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from factor_factory.research_org.contracts import stable_json_hash

ROUTER_CONTRACT_VERSION = "factorforge_research_domain_route_v1"


@dataclass(frozen=True)
class RoutingTerm:
    term: str
    weight: float = 1.0


DOMAIN_TERMS: dict[str, tuple[RoutingTerm, ...]] = {
    "fundamental": tuple(
        RoutingTerm(term, weight)
        for term, weight in (
            ("dcf", 3.0),
            ("discounted cash flow", 3.0),
            ("residual income", 3.0),
            ("free cash flow", 2.5),
            ("cash flow", 2.0),
            ("earnings", 2.0),
            ("profitability", 2.0),
            ("roe", 2.0),
            ("roic", 2.0),
            ("valuation", 2.0),
            ("balance sheet", 2.0),
            ("accounting", 2.0),
            ("debt", 1.5),
            ("fundamental", 2.0),
            ("基本面", 2.5),
            ("现金流", 2.5),
            ("自由现金流", 3.0),
            ("估值", 2.0),
            ("盈利", 2.0),
            ("利润", 1.5),
            ("资产负债", 2.0),
            ("会计", 2.0),
        )
    ),
    "price_volume": tuple(
        RoutingTerm(term, weight)
        for term, weight in (
            ("ohlcv", 3.0),
            ("price volume", 2.5),
            ("order flow", 2.5),
            ("microstructure", 2.5),
            ("intraday", 2.0),
            ("minute", 2.0),
            ("liquidity", 2.0),
            ("turnover", 1.8),
            ("momentum", 1.5),
            ("reversal", 1.5),
            ("volatility", 1.5),
            ("amplitude", 1.5),
            ("volume", 1.2),
            ("close", 0.8),
            ("open", 0.8),
            ("量价", 2.5),
            ("分钟", 2.0),
            ("成交量", 2.0),
            ("换手", 1.8),
            ("流动性", 2.0),
            ("振幅", 1.8),
            ("动量", 1.5),
            ("反转", 1.5),
            ("微观结构", 2.5),
        )
    ),
    "event_text": tuple(
        RoutingTerm(term, weight)
        for term, weight in (
            ("announcement", 2.5),
            ("disclosure", 2.5),
            ("news", 2.0),
            ("sentiment", 2.0),
            ("event study", 2.5),
            ("overnight information", 2.5),
            ("text", 1.2),
            ("公告", 2.5),
            ("新闻", 2.0),
            ("消息", 1.8),
            ("舆情", 2.0),
            ("事件", 1.5),
            ("隔夜信息", 2.5),
        )
    ),
    "macro_cross_asset": tuple(
        RoutingTerm(term, weight)
        for term, weight in (
            ("macro", 2.0),
            ("interest rate", 2.0),
            ("yield curve", 2.5),
            ("inflation", 2.0),
            ("commodity", 2.0),
            ("cross asset", 2.5),
            ("fx", 1.5),
            ("宏观", 2.0),
            ("利率", 2.0),
            ("收益率曲线", 2.5),
            ("通胀", 2.0),
            ("商品", 1.8),
            ("跨资产", 2.5),
        )
    ),
}

SOURCE_WEIGHTS = {
    "title": 3.0,
    "hypothesis": 4.0,
    "research_direction": 3.0,
    "decision": 3.0,
    "report": 2.5,
    "formula": 1.0,
    "code": 1.0,
}
MECHANISM_SOURCE_KINDS = frozenset(
    {"hypothesis", "research_direction", "decision", "report"}
)
ACTIVE_DOMAINS = {"fundamental", "price_volume"}

_CODE_SHAPE_RE = re.compile(
    r"(?:^|\n)\s*(?:def|class|import|from|return|for|while|if)\b|"
    r"(?:=>|:=|==|!=|\b(?:lambda|function)\b)",
    re.IGNORECASE,
)
_FORMULA_CALL_RE = re.compile(
    r"\b(?:ts_[a-z0-9_]+|rank|normalize|standardize|log|exp|sqrt|abs)\s*\(",
    re.IGNORECASE,
)
_FORMULA_TOKEN_RE = re.compile(
    r"\b(?:open|high|low|close|volume|amount|turnover|returns?|pct_chg|change_pct)\b",
    re.IGNORECASE,
)
_MECHANISM_RELATION_MARKERS = (
    "because",
    "therefore",
    "causes",
    "cause",
    "drives",
    "drive",
    "affects",
    "affect",
    "reveals",
    "reveal",
    "reflects",
    "reflect",
    "captures",
    "capture",
    "compensates",
    "compensate",
    "absorbs",
    "absorb",
    "forces",
    "forced",
    "estimate",
    "discount",
    "supports",
    "support",
    "predicts",
    "predict",
    "reverses",
    "reverse",
    "导致",
    "驱动",
    "反映",
    "揭示",
    "刻画",
    "补偿",
    "吸收",
    "迫使",
    "由于",
    "因为",
    "因而",
    "形成",
    "估计",
    "折现",
    "支持",
    "预测",
)
_MECHANISM_OBJECT_MARKERS = (
    "investor",
    "trader",
    "buyer",
    "seller",
    "supplier",
    "firm",
    "creditor",
    "shareholder",
    "cash flow",
    "valuation",
    "risk premium",
    "liquidity",
    "order flow",
    "pressure",
    "information",
    "announcement",
    "disclosure",
    "demand",
    "supply",
    "constraint",
    "投资者",
    "交易者",
    "买方",
    "卖方",
    "付款方",
    "公司",
    "债权人",
    "股东",
    "现金流",
    "估值",
    "风险溢价",
    "流动性",
    "订单流",
    "资金流",
    "压力",
    "信息",
    "公告",
    "需求",
    "供给",
    "约束",
)
_MECHANISM_TARGET_MARKERS = (
    "future return",
    "expected return",
    "return premium",
    "risk premium",
    "reversal",
    "reverse",
    "momentum",
    "mispricing",
    "price pressure",
    "trading pressure",
    "forced selling",
    "liquidity premium",
    "crowding",
    "valuation gap",
    "intrinsic value",
    "discount",
    "premium",
    "spread",
    "alpha",
    "pressure",
    "未来收益",
    "预期收益",
    "收益溢价",
    "风险溢价",
    "反转",
    "动量",
    "错误定价",
    "价格压力",
    "交易压力",
    "被迫卖出",
    "流动性溢价",
    "拥挤",
    "估值差",
    "内在价值",
    "折价",
    "溢价",
    "价差",
    "压力",
)
_DESCRIPTIVE_DATA_RE = re.compile(
    r"(?:\b(?:data(?:set)?|report|table|file|fields?|columns?)\b.{0,100}"
    r"\b(?:is|are|was|were|contains?|includes?|consists?|available|listed|recorded)\b|"
    r"\b(?:contains?|includes?|lists?|records?)\b.{0,100}"
    r"\b(?:data(?:set)?|fields?|columns?|price|volume|turnover|returns?)\b|"
    r"(?:数据|数据集|报告|表格|文件|字段|列).{0,60}(?:可用|包含|包括|记录|列出|存在))",
    re.IGNORECASE,
)
_ENGLISH_RELATIONAL_CLAUSE_RE = re.compile(
    r"\b(?:causes?|caused|drives?|drove|affects?|affected|reveals?|revealed|"
    r"reflects?|reflected|captures?|captured|compensates?|compensated|"
    r"absorbs?|absorbed|forces|predicts?|predicted|reverses|reversed|"
    r"estimates|estimated|discounts|supports|supported|determines|determined)\b\s+"
    r"(?!(?:fields?|columns?|data(?:set)?|variables?)\b)[a-z]"
    r"|\b(?:may|might|can|could|will|would|should|must|to)\s+"
    r"(?:cause|drive|affect|reveal|reflect|capture|compensate|absorb|force|"
    r"predict|reverse|estimate|discount|support|determine)\b\s+"
    r"(?!(?:fields?|columns?|data(?:set)?|variables?)\b)[a-z]"
    r"|\b(?:cash\s+flows?|earnings|liquidity|order\s+flow|selling\s+pressure|"
    r"demand|supply|investors?|traders?|firms?|suppliers?)\s+"
    r"(?:cause|drive|affect|reveal|reflect|capture|compensate|absorb|force|"
    r"predict|reverse|estimate|discount|support|determine)\b\s+"
    r"(?!(?:levels?|rates?|fields?|columns?|data(?:set)?|variables?)\b)[a-z]"
    r"|\b(?:because|therefore)\b\s+[a-z]",
    re.IGNORECASE,
)
_CHINESE_RELATIONAL_CLAUSE_RE = re.compile(
    r"(?:导致|驱动|反映|揭示|刻画|补偿|吸收|迫使|预测|折现|估计)"
    r"(?!字段|列|数据|指标)[^\s、，,；;：:]{1,}"
    r"|(?:因为|由于)[^\s、，,；;：:]{1,}"
)


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _contains(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9_ ]+", term):
        escaped = re.escape(term).replace(r"\ ", r"\s+")
        return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text) is not None
    return term in text


def _excerpt(text: str, term: str, *, limit: int = 140) -> str:
    index = text.find(term)
    if index < 0:
        return text[:limit]
    start = max(0, index - 45)
    end = min(len(text), index + len(term) + 75)
    value = " ".join(text[start:end].split())
    return value[:limit]


def _source_content_classification(text: str) -> dict[str, Any]:
    normalized = _normalized(text).strip()
    relation_hits = sorted(
        marker for marker in _MECHANISM_RELATION_MARKERS if marker in normalized
    )
    object_hits = sorted(
        marker for marker in _MECHANISM_OBJECT_MARKERS if marker in normalized
    )
    target_hits = sorted(
        marker for marker in _MECHANISM_TARGET_MARKERS if marker in normalized
    )
    word_count = len(re.findall(r"[a-z][a-z0-9_-]*", normalized))
    han_count = len(re.findall(r"[\u3400-\u9fff]", normalized))
    code_like = _CODE_SHAPE_RE.search(normalized) is not None
    formula_calls = len(_FORMULA_CALL_RE.findall(normalized))
    formula_tokens = len(_FORMULA_TOKEN_RE.findall(normalized))
    arithmetic_symbols = len(re.findall(r"[+*/=]", normalized))
    formula_like = bool(
        formula_calls
        or (
            formula_tokens >= 2
            and arithmetic_symbols >= 1
            and not relation_hits
        )
    )
    prose_budget_satisfied = word_count >= 6 or han_count >= 12
    relational_clause_present = bool(
        _ENGLISH_RELATIONAL_CLAUSE_RE.search(normalized)
        or _CHINESE_RELATIONAL_CLAUSE_RE.search(normalized)
    )
    complete_mechanism_triple = bool(
        relation_hits
        and object_hits
        and target_hits
        and relational_clause_present
    )
    descriptive_inventory = _DESCRIPTIVE_DATA_RE.search(normalized) is not None
    descriptive_data_only = bool(
        descriptive_inventory and not complete_mechanism_triple
    )
    mechanism_bearing = bool(
        not code_like
        and not formula_like
        and not descriptive_data_only
        and prose_budget_satisfied
        and complete_mechanism_triple
    )
    if code_like:
        content_class = "code"
    elif formula_like:
        content_class = "formula"
    elif mechanism_bearing:
        content_class = "mechanism_prose"
    elif prose_budget_satisfied:
        content_class = "descriptive_prose"
    else:
        content_class = "short_or_unclassified"
    return {
        "content_class": content_class,
        "mechanism_bearing": mechanism_bearing,
        "relation_markers": relation_hits[:8],
        "economic_object_markers": object_hits[:8],
        "target_state_markers": target_hits[:8],
        "relational_clause_present": relational_clause_present,
        "descriptive_data_only": descriptive_data_only,
    }


def routing_sources(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    input_kind = str(request.get("input_kind") or "hypothesis")
    if input_kind not in SOURCE_WEIGHTS or input_kind == "title":
        input_kind = "hypothesis"
    for kind, key in (("title", "title"), (input_kind, "hypothesis")):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            sources.append(
                {
                    "kind": kind,
                    "text": text,
                    "origin": key,
                    **_source_content_classification(text),
                }
            )
    snapshot = request.get("conversation_snapshot")
    messages = snapshot.get("messages") if isinstance(snapshot, Mapping) else None
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, Mapping) or message.get("role") != "user":
                continue
            value = message.get("content")
            if not isinstance(value, str) or not value.strip():
                continue
            raw_kind = message.get("content_kind")
            kind = str(raw_kind) if raw_kind else "research_direction"
            if kind not in SOURCE_WEIGHTS:
                kind = "unclassified"
            text = value.strip()
            sources.append(
                {
                    "kind": kind,
                    "text": text,
                    "origin": f"conversation:{message.get('sequence_no') or '?'}",
                    **_source_content_classification(text),
                }
            )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["kind"], _normalized(source["text"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _routing_input_projection(sources: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "kind": str(source.get("kind") or ""),
            "origin": str(source.get("origin") or ""),
            "text_sha256": stable_json_hash(str(source.get("text") or "")),
            "content_class": str(source.get("content_class") or ""),
            "mechanism_bearing": source.get("mechanism_bearing") is True,
            "relation_markers": list(source.get("relation_markers") or []),
            "economic_object_markers": list(
                source.get("economic_object_markers") or []
            ),
            "target_state_markers": list(
                source.get("target_state_markers") or []
            ),
            "relational_clause_present": (
                source.get("relational_clause_present") is True
            ),
            "descriptive_data_only": source.get("descriptive_data_only") is True,
        }
        for source in sources
    ]
    return {"sources": rows, "source_count": len(rows)}


def route_research_request(request: Mapping[str, Any]) -> dict[str, Any]:
    sources = routing_sources(request)
    scores = {domain: 0.0 for domain in DOMAIN_TERMS}
    exploratory_scores = {domain: 0.0 for domain in DOMAIN_TERMS}
    evidence: list[dict[str, Any]] = []
    matched_sources: dict[str, set[str]] = {domain: set() for domain in DOMAIN_TERMS}
    exploratory_sources: dict[str, set[str]] = {
        domain: set() for domain in DOMAIN_TERMS
    }
    exploratory_origins: dict[str, set[str]] = {
        domain: set() for domain in DOMAIN_TERMS
    }
    exploratory_terms: dict[str, set[str]] = {
        domain: set() for domain in DOMAIN_TERMS
    }
    for source in sources:
        normalized = _normalized(source["text"])
        source_weight = SOURCE_WEIGHTS.get(source["kind"], 1.0)
        routing_eligible = bool(
            source["kind"] in MECHANISM_SOURCE_KINDS
            and source.get("mechanism_bearing") is True
        )
        for domain, terms in DOMAIN_TERMS.items():
            for term in terms:
                normalized_term = _normalized(term.term)
                if not _contains(normalized, normalized_term):
                    continue
                contribution = source_weight * term.weight
                if routing_eligible:
                    scores[domain] += contribution
                    matched_sources[domain].add(source["kind"])
                else:
                    exploratory_scores[domain] += contribution
                    exploratory_sources[domain].add(source["kind"])
                    exploratory_origins[domain].add(source["origin"])
                    exploratory_terms[domain].add(term.term)
                evidence.append(
                    {
                        "domain": domain,
                        "source_kind": source["kind"],
                        "source_origin": source["origin"],
                        "matched_term": term.term,
                        "score_contribution": round(contribution, 4),
                        "routing_eligible": routing_eligible,
                        "content_class": source.get("content_class"),
                        "public_excerpt": _excerpt(normalized, normalized_term),
                    }
                )
    ordered = sorted(scores, key=lambda domain: (-scores[domain], domain))
    lead = ordered[0] if ordered and scores[ordered[0]] > 0 else None
    supporting: list[str] = []
    if lead:
        lead_score = scores[lead]
        for domain in ordered[1:]:
            if scores[domain] >= max(4.0, lead_score * 0.55):
                supporting.append(domain)
    if lead is None:
        route_state = "UNDER_SPECIFIED"
        confidence = "none"
    else:
        second_score = scores[ordered[1]] if len(ordered) > 1 else 0.0
        gap_ratio = (scores[lead] - second_score) / max(scores[lead], 1.0)
        source_diversity = len(matched_sources[lead])
        if gap_ratio >= 0.55 and source_diversity >= 2:
            confidence = "high"
        elif gap_ratio >= 0.25 or source_diversity >= 2:
            confidence = "moderate"
        else:
            confidence = "low"
        selected = [lead, *supporting]
        unavailable = [domain for domain in selected if domain not in ACTIVE_DOMAINS]
        if lead not in ACTIVE_DOMAINS:
            route_state = "WAITING_CAPABILITY"
        elif unavailable:
            route_state = "ROUTED_WITH_CAPABILITY_GAP"
        else:
            route_state = "ROUTED"
    exploratory_candidates = [
        {
            "domain": domain,
            "score": round(exploratory_scores[domain], 4),
            "source_kinds": sorted(exploratory_sources[domain]),
            "source_origins": sorted(exploratory_origins[domain]),
            "matched_terms": sorted(exploratory_terms[domain]),
        }
        for domain in sorted(
            DOMAIN_TERMS,
            key=lambda item: (-exploratory_scores[item], item),
        )
        if exploratory_scores[domain] > 0
    ]
    claimed_mechanism_sources = [
        source for source in sources if source["kind"] in MECHANISM_SOURCE_KINDS
    ]
    eligible_sources = [
        source
        for source in claimed_mechanism_sources
        if source.get("mechanism_bearing") is True
    ]
    gate_reasons: list[str] = []
    if not eligible_sources:
        gate_reasons.append("NO_MECHANISM_BEARING_USER_EVIDENCE")
    elif lead is None:
        gate_reasons.append("NO_DOMAIN_MATCH_IN_MECHANISM_BEARING_USER_EVIDENCE")
    else:
        gate_reasons.append("MECHANISM_DOMAIN_MATCH_PRESENT")
    if any(
        source.get("mechanism_bearing") is not True
        for source in claimed_mechanism_sources
    ):
        gate_reasons.append(
            "CLAIMED_MECHANISM_MODALITY_REJECTED_BY_CONTENT_GATE"
        )
    if exploratory_candidates:
        gate_reasons.append("EXPLORATORY_LEXICAL_MATCHES_EXCLUDED_FROM_DOMAIN_SELECTION")
    projection = _routing_input_projection(sources)
    return {
        "contract_version": ROUTER_CONTRACT_VERSION,
        "routing_input_sha256": stable_json_hash(projection),
        "routing_input_projection": projection,
        "route_state": route_state,
        "lead_domain": lead,
        "supporting_domains": supporting,
        "routing_confidence": confidence,
        "domain_scores": {key: round(value, 4) for key, value in sorted(scores.items())},
        "exploratory_domain_scores": {
            key: round(value, 4) for key, value in sorted(exploratory_scores.items())
        },
        "exploratory_candidates": exploratory_candidates,
        "mechanism_gate": {
            "passed": lead is not None,
            "eligible_source_kinds": sorted(
                {source["kind"] for source in eligible_sources}
            ),
            "eligible_source_origins": sorted(
                {source["origin"] for source in eligible_sources}
            ),
            "rejected_claimed_source_origins": sorted(
                {
                    source["origin"]
                    for source in claimed_mechanism_sources
                    if source.get("mechanism_bearing") is not True
                }
            ),
            "reasons": gate_reasons,
        },
        "evidence": sorted(
            evidence,
            key=lambda item: (
                not bool(item["routing_eligible"]),
                -float(item["score_contribution"]),
                item["domain"],
                item["source_origin"],
            ),
        )[:40],
        "capability_gaps": [
            domain
            for domain in ([lead] if lead else []) + supporting
            if domain not in ACTIVE_DOMAINS
        ],
        "routing_policy": {
            "economic_and_research_text_precedes_formula_or_code": True,
            "mechanism_evidence_required_for_domain_activation": True,
            "mechanism_modality_is_content_verified_not_caller_trusted": True,
            "exploratory_lexical_matches_do_not_activate_domains": True,
            "operator_names_do_not_select_math_family": True,
            "mixed_routes_allow_independent_parallel_proposals": True,
            "unsupported_lead_domain_fails_closed": True,
        },
    }
