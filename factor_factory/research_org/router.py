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
ACTIVE_DOMAINS = {"fundamental", "price_volume"}


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


def routing_sources(request: Mapping[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for kind, key in (("title", "title"), ("hypothesis", "hypothesis")):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            sources.append({"kind": kind, "text": value.strip(), "origin": key})
    snapshot = request.get("conversation_snapshot")
    messages = snapshot.get("messages") if isinstance(snapshot, Mapping) else None
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, Mapping) or message.get("role") != "user":
                continue
            value = message.get("content")
            if not isinstance(value, str) or not value.strip():
                continue
            kind = str(message.get("content_kind") or "research_direction")
            if kind == "hypothesis":
                kind = "hypothesis"
            elif kind not in SOURCE_WEIGHTS:
                kind = "research_direction"
            sources.append(
                {
                    "kind": kind,
                    "text": value.strip(),
                    "origin": f"conversation:{message.get('sequence_no') or '?'}",
                }
            )
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["kind"], _normalized(source["text"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _routing_input_projection(sources: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    rows = [
        {
            "kind": str(source.get("kind") or ""),
            "origin": str(source.get("origin") or ""),
            "text_sha256": stable_json_hash(str(source.get("text") or "")),
        }
        for source in sources
    ]
    return {"sources": rows, "source_count": len(rows)}


def route_research_request(request: Mapping[str, Any]) -> dict[str, Any]:
    sources = routing_sources(request)
    scores = {domain: 0.0 for domain in DOMAIN_TERMS}
    evidence: list[dict[str, Any]] = []
    matched_sources: dict[str, set[str]] = {domain: set() for domain in DOMAIN_TERMS}
    for source in sources:
        normalized = _normalized(source["text"])
        source_weight = SOURCE_WEIGHTS.get(source["kind"], 1.0)
        for domain, terms in DOMAIN_TERMS.items():
            for term in terms:
                normalized_term = _normalized(term.term)
                if not _contains(normalized, normalized_term):
                    continue
                contribution = source_weight * term.weight
                scores[domain] += contribution
                matched_sources[domain].add(source["kind"])
                evidence.append(
                    {
                        "domain": domain,
                        "source_kind": source["kind"],
                        "source_origin": source["origin"],
                        "matched_term": term.term,
                        "score_contribution": round(contribution, 4),
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
        "evidence": sorted(
            evidence,
            key=lambda item: (-float(item["score_contribution"]), item["domain"], item["source_origin"]),
        )[:40],
        "capability_gaps": [
            domain
            for domain in ([lead] if lead else []) + supporting
            if domain not in ACTIVE_DOMAINS
        ],
        "routing_policy": {
            "economic_and_research_text_precedes_formula_or_code": True,
            "operator_names_do_not_select_math_family": True,
            "mixed_routes_allow_independent_parallel_proposals": True,
            "unsupported_lead_domain_fails_closed": True,
        },
    }
