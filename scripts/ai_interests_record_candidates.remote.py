#!/usr/bin/env python3
"""
ai_interests_record_candidates.py — Candidate Normalizer (LLM-augmented)
=========================================================================
Role in main chain: candidate_normalizer (canonical node)

Reads TWO sources and merges into a unified candidates.csv:
  1. watcher_candidates.json  — structured output from ai_interests_market_watcher.sh
     Path: {base_dir}/output/ai_interests/watchers/watcher_candidates-{ts}.json
     (uses the latest one)

  2. heat_history.csv          — historical heat records from ai_interests_heat_history_record.py
     Path: {base_dir}/output/ai_interests/heat_history/heat_history.csv

Normalization pipeline (two-stage):
  Stage 1 — Rule-based canonical map (CANONICAL_MAP):
    - Fast, deterministic, always tried first
    - Iran/Hormuz/Oil transport cluster → "伊朗/霍尔木兹/油运"
    - Middle-East conflict cluster → "中东冲突/红海"
    - etc.

  Stage 2 — LLM-assisted裁决 (call_llm_normalize):
    - Triggered ONLY when Stage 1 cannot resolve:
        (a) raw_topic has no entry in CANONICAL_MAP AND partial scan fails
        (b) conflict: same raw string maps to multiple different canonicals via partial scan
        (c) raw_topic is an unknown compound/new signal not covered by any rule
    - Decider/curator does NOT do naming裁决 — that is this node's job

Output: {base_dir}/output/ai_interests/candidates.csv
  Fields: topic, decision, current_heat, history_baseline, heat_gradient,
          source_count, item_count, fact_strength, asset_mapping_strength,
          priced_in_hint, reason, decision_source, llm_reason,
          timestamp_utc, sources_raw

Canonical name mapping (aliases → canonical):
"""
import argparse
import csv
import json
import os
import re
import sys
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Canonical name map ─────────────────────────────────────────────────────────
CANONICAL_MAP: Dict[str, str] = {
    # Iran / Hormuz / Oil transport cluster
    "伊朗": "伊朗/霍尔木兹/油运",
    "霍尔木兹": "伊朗/霍尔木兹/油运",
    "霍尔木兹海峡": "伊朗/霍尔木兹/油运",
    "油运": "伊朗/霍尔木兹/油运",
    "原油运输": "伊朗/霍尔木兹/油运",
    "油轮": "伊朗/霍尔木兹/油运",
    "原油": "伊朗/霍尔木兹/油运",
    "OPEC": "伊朗/霍尔木兹/油运",
    "中东原油": "伊朗/霍尔木兹/油运",
    "能源运输": "伊朗/霍尔木兹/油运",
    "LNG运输": "伊朗/霍尔木兹/油运",
    # Middle east conflict cluster
    "中东冲突": "中东冲突/红海",
    "中东局势": "中东冲突/红海",
    "红海": "中东冲突/红海",
    "胡塞": "中东冲突/红海",
    "曼德海峡": "中东冲突/红海",
    "中东": "中东冲突/红海",
    "沙伊": "中东冲突/红海",
    "以色列": "中东冲突/红海",
    "加沙": "中东冲突/红海",
    # Energy security cluster
    "能源安全": "能源安全/能源转型",
    "能源转型": "能源安全/能源转型",
    "LNG": "能源安全/能源转型",
    "天然气": "能源安全/能源转型",
    "欧洲能源": "能源安全/能源转型",
    "俄乌": "能源安全/能源转型",
    "俄乌冲突": "能源安全/能源转型",
    # Tech topics
    "AI": "AI与算力链",
    "ai": "AI与算力链",
    "AI与算力链": "AI与算力链",
    "ai与算力链": "AI与算力链",
    "算力": "AI与算力链",
    "人工智能": "AI与算力链",
    "大模型": "AI与算力链",
    "AI算力": "AI与算力链",
    "数据中心": "能源电力/数据中心",
    "核电": "能源电力/数据中心",
    "电网": "能源电力/数据中心",
    "液冷": "AI与算力链",
    "光模块": "光子芯片/光互连",
    "硅光": "光子芯片/光互连",
    "CPO": "光子芯片/光互连",
    "光子芯片": "光子芯片/光互连",
    "Agent": "Agent/AI工具链",
    "agent": "Agent/AI工具链",
    "Agent/AI工具链": "Agent/AI工具链",
    "agent/ai工具链": "Agent/AI工具链",
    "智能体": "Agent/AI工具链",
    "AI工具": "Agent/AI工具链",
    "OpenClaw": "Agent/AI工具链",
    "存储": "存储",
    "DRAM": "存储",
    "NAND": "存储",
    "HBM": "存储",
    "中美联动": "中美联动",
    "中美": "中美联动",
    "关税": "中美联动",
    "出口管制": "中美联动",
    "制裁": "中美联动",
    # Additional aliases from watcher script
    "全球宏观/美联储": "全球宏观/美联储",
    "美联储": "全球宏观/美联储",
    "降息": "全球宏观/美联储",
    "俄乌/欧洲能源": "能源安全/能源转型",
    "欧洲能源": "能源安全/能源转型",
}

# Canonical topic display names (ordered for output priority)
CANONICAL_TOPICS = [
    "AI与算力链",
    "存储",
    "光子芯片/光互连",
    "Agent/AI工具链",
    "能源电力/数据中心",
    "伊朗/霍尔木兹/油运",
    "中东冲突/红海",
    "能源安全/能源转型",
    "中美联动",
    "全球宏观/美联储",
]

# Asset mapping strength per canonical topic
ASSET_STRENGTH: Dict[str, int] = {
    "AI与算力链": 3,
    "存储": 2,
    "光子芯片/光互连": 2,
    "Agent/AI工具链": 1,
    "能源电力/数据中心": 2,
    "伊朗/霍尔木兹/油运": 3,
    "中东冲突/红海": 3,
    "能源安全/能源转型": 2,
    "中美联动": 3,
    "全球宏观/美联储": 2,
}

# Source quality weight for fact_strength boost
SOURCE_QUALITY = {
    "eastmoney_mx_search": 1,
    "hexin_news_mcp": 1,
    "trendradar_topic_pipeline": 1,
    "finnewsaireader_signals": 1,
    "watcher_structured_probe": 1,
    "watcher_market_watcher": 1,
    "llm_hotspot_scout": 2,
}

FIELDS = [
    "topic", "decision", "current_heat", "history_baseline",
    "heat_gradient", "source_count", "item_count",
    "fact_strength", "asset_mapping_strength", "priced_in_hint",
    "reason", "decision_source", "llm_reason",
    "timestamp_utc", "sources_raw",
    "priority_tier", "cluster_strength", "lifecycle_state", "anchor_stock_code",
    "related_stock_count", "hot_rank_overlap_count",
]

# Decision thresholds
GRADIENT_RAISE = 2.0
GRADIENT_LOWER = -2.0
HEAT_EMERGE = 6
HEAT_DROP = 2
MIN_SOURCES = 2

# ── LLM client (lazy import, only used when Stage-2 is triggered) ───────────────
_llm_client = None


def _get_llm_client():
    """Lazy LLM client via MiniMaxTokenPlanClient (workspace lib).

    Reads MINIMAX_API_KEY from environment.
    Uses MiniMax Token Plan endpoint: https://api.minimaxi.com/anthropic
    Model: anthropic/MiniMax-M2.7

    No DeepSeek path, no docker/.env AI_API_KEY lookup.
    """
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    api_key = os.environ.get("MINIMAX_API_KEY", "").strip() or os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        for env_path in [
            Path(__file__).resolve().parents[1] / "docker" / ".env",
            Path(__file__).resolve().parents[1] / ".env",
            Path("/home/ubuntu/.openclaw/workspace/docker/.env"),
            Path("/home/ubuntu/.openclaw/workspace/.env"),
        ]:
            if not env_path.exists():
                continue
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() in {"MINIMAX_API_KEY", "AI_API_KEY"} and v.strip():
                    api_key = v.strip().strip('\"').strip("'")
                    break
            if api_key:
                break
    if not api_key:
        print("[normalizer] WARNING: MINIMAX_API_KEY/AI_API_KEY not set — LLM fallback disabled", file=sys.stderr)
        return None
    os.environ.setdefault("MINIMAX_API_KEY", api_key)
    os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

    try:
        import sys as _sys
        _sys.path.insert(0, "/home/ubuntu/.openclaw/workspace/lib")
        from llm_clients import MiniMaxTokenPlanClient
        _llm_client = MiniMaxTokenPlanClient(
            api_key=api_key,
            # base_url defaults to https://api.minimaxi.com/anthropic
            # model  defaults to anthropic/MiniMax-M2.7
        )
        print("[normalizer] LLM client ready: MiniMaxTokenPlanClient (anthropic/MiniMax-M2.7)", file=sys.stderr)
        return _llm_client
    except Exception as e:
        print(f"[normalizer] WARNING: MiniMaxTokenPlanClient init failed: {e} — LLM fallback disabled", file=sys.stderr)
        return None


# ── Stage-1: Rule-based canonical normalization ───────────────────────────────

def normalize_to_canonical(raw_topic: str) -> Tuple[str, str]:
    """Collapse raw topic/keyword to canonical name using CANONICAL_MAP.

    Returns:
        (canonical_name, decision_source)
        decision_source is always "rule" for Stage-1
    """
    raw_topic = (raw_topic or '').strip()
    lowered = raw_topic.lower()

    # Direct canonical lookup
    if raw_topic in CANONICAL_MAP:
        return CANONICAL_MAP[raw_topic], "rule"
    if lowered in CANONICAL_MAP:
        return CANONICAL_MAP[lowered], "rule"

    # Partial scan — check if any alias is inside raw_topic or vice versa
    candidates: Dict[str, int] = defaultdict(int)
    for alias, canonical in CANONICAL_MAP.items():
        alias_low = alias.lower()
        if alias in raw_topic or raw_topic in alias or alias_low in lowered or lowered in alias_low:
            candidates[canonical] += len(alias)  # weight by alias length

    if candidates:
        # If all candidates agree → deterministic
        unique_canonicals = set(candidates.keys())
        if len(unique_canonicals) == 1:
            return list(unique_canonicals)[0], "rule"
        # Conflict: same raw string maps to multiple different canonicals
        return "", "conflict"  # signals Stage-2 needed

    # No match at all
    return "", "unknown"


# ── Stage-2: LLM-assisted normalization ───────────────────────────────────────

LLM_NORMALIZE_PROMPT_TEMPLATE = """\
你是一个金融投资领域的 AI 热点主题命名裁判。

【任务】
给定一个原始候选主题名称（可能来自新闻关键词、用户输入、或 watcher 探针信号），
请将其归一化到以下已知 canonical 主题之一，或者判断它是否是一个全新的、值得新增的主题。

【已知 canonical 主题清单】
{canonical_list}

【已知 alias → canonical 映射（供参考）】
{alias_samples}

【原始候选主题】
{raw_topic}

【输出格式要求】
请以纯 JSON 格式输出，不要包含任何解释性文字，只输出以下字段：
{{
  "canonical_name": "归一化后的主题名，如果无法归入任何已知主题则填入原始候选名",
  "decision": "absorb | new_topic | keep_raw",
  "reason": "一句话裁决理由，简洁明确",
  "confidence": "high | medium | low"
}}

【decision 含义】
- absorb: 该候选应归入某个已知 canonical 主题
- new_topic: 这是一个全新的、值得单独跟踪的主题（请在 canonical_name 中给出新主题名）
- keep_raw: 既无法归入已知主题，也不值得新增，保持原样

请直接输出 JSON：\
"""


def call_llm_normalize(raw_topic: str) -> Tuple[str, str]:
    """Call LLM to resolve an unknown/conflicting raw topic.

    Returns:
        (canonical_name, llm_reason)

    If LLM is unavailable, returns (raw_topic, "llm_unavailable — kept raw").
    """
    client = _get_llm_client()
    if client is None:
        return raw_topic, "llm_unavailable — kept raw"

    # Build canonical list string
    canonical_list_str = "\n".join(f"  - {t}" for t in CANONICAL_TOPICS)

    # Sample a few key aliases for context (don't dump all 80+ lines)
    alias_samples = []
    for alias, canon in list(CANONICAL_MAP.items())[:30]:
        alias_samples.append(f"  {alias!r} → {canon!r}")
    alias_samples_str = "\n".join(alias_samples)

    prompt = LLM_NORMALIZE_PROMPT_TEMPLATE.format(
        canonical_list=canonical_list_str,
        alias_samples=alias_samples_str,
        raw_topic=raw_topic,
    )

    try:
        content = client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            timeout=60,
        )

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
            if content.endswith("```"):
                content = content[:-3].strip()

        # Try direct JSON parse first
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # MiniMax may return free-form text instead of strict JSON.
            # Attempt to extract a JSON object by finding balanced braces.
            import re as _re
            brace_start = content.find("{")
            if brace_start != -1:
                # Try extending from each { to find a parseable object
                for end_offset in range(brace_start + 1, len(content) + 1):
                    candidate = content[brace_start:end_offset]
                    try:
                        result = json.loads(candidate)
                        content = candidate  # update content for fence-strip logic below
                        break
                    except json.JSONDecodeError:
                        continue
                else:
                    return raw_topic, f"llm_non_json (MiniMax returned non-JSON, kept raw): {content[:200]}"
            else:
                return raw_topic, f"llm_non_json (MiniMax returned non-JSON, kept raw): {content[:200]}"

        canonical_name = result.get("canonical_name", raw_topic)
        reason = result.get("reason", "")
        decision = result.get("decision", "keep_raw")
        confidence = result.get("confidence", "low")

        full_reason = f"[LLM] decision={decision} confidence={confidence} | {reason}"
        return canonical_name, full_reason

    except Exception as e:
        return raw_topic, f"llm_error={e} — kept raw"


def resolve_canonical(raw_topic: str) -> Tuple[str, str, str]:
    """Two-stage canonical resolution.

    Returns:
        (canonical_name, decision_source, llm_reason)

    decision_source values:
        rule    — resolved by CANONICAL_MAP (Stage 1)
        llm     — resolved by LLM (Stage 2)
    """
    canonical, ds = normalize_to_canonical(raw_topic)

    if ds == "rule":
        return canonical, "rule", ""

    # Stage-2 triggers
    trigger = ds  # "conflict" or "unknown"
    print(f"[normalizer] LLM裁决触发: raw_topic={raw_topic!r} trigger={trigger}", file=sys.stderr)
    canonical, llm_reason = call_llm_normalize(raw_topic)
    return canonical, "llm", llm_reason


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class TopicSnapshot:
    topic: str                    # canonical name
    current_heat: float = 0.0
    history_baseline: float = 0.0
    heat_gradient: float = 0.0
    source_count: int = 0
    item_count: int = 0
    fact_strength: int = 0
    asset_mapping_strength: int = 0
    priced_in_hint: str = "undetermined"
    reason: str = ""
    decision_source: str = "rule"   # rule | llm
    llm_reason: str = ""             # populated when decision_source == "llm"
    timestamps: List[str] = field(default_factory=list)
    sources_raw: List[str] = field(default_factory=list)
    raw_candidates: List[str] = field(default_factory=list)
    priority_tier: str = ""
    cluster_strength: str = ""
    lifecycle_state: str = ""
    anchor_stock_code: str = ""
    related_stock_count: int = 0
    hot_rank_overlap_count: int = 0

    @property
    def decision(self) -> str:
        if self.priority_tier == 'P4_noise':
            return 'LOWER'
        if self.priority_tier == 'P1_core_resonating':
            return 'RAISE'
        if self.priority_tier == 'P2_core_single_anchor':
            if self.current_heat >= HEAT_EMERGE or self.hot_rank_overlap_count >= 1:
                return 'RAISE'
            return 'KEEP'
        if self.current_heat == 0 and self.heat_gradient == 0:
            return 'KEEP'
        if self.heat_gradient >= GRADIENT_RAISE and self.current_heat >= HEAT_EMERGE:
            return 'RAISE'
        if self.heat_gradient <= GRADIENT_LOWER and self.current_heat <= HEAT_DROP:
            return 'LOWER'
        if self.source_count < MIN_SOURCES:
            return 'KEEP'
        if self.current_heat >= HEAT_EMERGE and self.heat_gradient > 0:
            return 'KEEP'
        return 'KEEP'

    def build_reason(self) -> str:
        d = self.decision
        if self.priority_tier == 'P1_core_resonating':
            return (f"priority={self.priority_tier}, cluster={self.cluster_strength}, "
                    f"heat={self.current_heat:.0f}, overlap={self.hot_rank_overlap_count}, "
                    f"anchor={self.anchor_stock_code}")
        if self.priority_tier == 'P2_core_single_anchor':
            return (f"priority={self.priority_tier}, cluster={self.cluster_strength}, "
                    f"heat={self.current_heat:.0f}, overlap={self.hot_rank_overlap_count}, "
                    f"anchor={self.anchor_stock_code}")
        if self.priority_tier == 'P4_noise':
            return (f"priority={self.priority_tier}, cluster={self.cluster_strength}, "
                    f"heat={self.current_heat:.0f}, drop noise")
        if d == 'RAISE':
            return (f"gradient={self.heat_gradient:+.1f}>={GRADIENT_RAISE}, "
                    f"heat={self.current_heat:.0f}>={HEAT_EMERGE}, "
                    f"fact={self.fact_strength}, asset={self.asset_mapping_strength}")
        if d == 'LOWER':
            return (f"gradient={self.heat_gradient:+.1f}<={GRADIENT_LOWER}, "
                    f"heat={self.current_heat:.0f}<={HEAT_DROP}")
        if self.source_count < MIN_SOURCES:
            return f"source_count={self.source_count}<{MIN_SOURCES} (noise)"
        return (f"gradient={self.heat_gradient:+.1f} normal, heat={self.current_heat:.0f}, "
                f"fact={self.fact_strength}, asset={self.asset_mapping_strength}")


# ── Source loaders ─────────────────────────────────────────────────────────────

def _latest_watcher_json(out_dir: Path) -> Path | None:
    """Find the most recent watcher_candidates JSON."""
    watchers_dir = out_dir / "watchers"
    if not watchers_dir.exists():
        return None
    files = sorted(watchers_dir.glob("watcher_candidates-*.json"), reverse=True)
    return files[0] if files else None


def _load_watcher_candidates(watcher_path: Path) -> Dict[str, TopicSnapshot]:
    """Load and normalize candidates from watcher JSON.

    For each entry, Stage-1 is tried first; Stage-2 LLM is triggered
    only when Stage-1 returns conflict/unknown.
    """
    if watcher_path is None or not watcher_path.exists():
        return {}
    with watcher_path.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    candidates = doc.get("candidates", [])
    snapshots: Dict[str, TopicSnapshot] = {}

    for entry in candidates:
        raw_name = entry.get("canonical_name", "")
        canonical, ds, llm_reason = resolve_canonical(raw_name)

        if canonical not in snapshots:
            snapshots[canonical] = TopicSnapshot(
                topic=canonical,
                decision_source=ds,
                llm_reason=llm_reason,
            )
        snap = snapshots[canonical]

        # Track raw candidates for audit
        if raw_name not in snap.raw_candidates:
            snap.raw_candidates.append(raw_name)

        # Use the most informative decision_source (llm > rule)
        if ds == "llm":
            snap.decision_source = "llm"
            if llm_reason:
                snap.llm_reason = llm_reason

        heat = float(entry.get("heat_proxy", 0))
        snap.current_heat = max(snap.current_heat, heat)
        snap.item_count += int(entry.get("item_count", 0))
        src = entry.get("source", "unknown")
        if src not in snap.sources_raw:
            snap.sources_raw.append(src)
        entry_source_count = _to_int(entry.get("source_count", 0), 0)
        snap.source_count = max(len(snap.sources_raw), entry_source_count)
        entry_fact_strength = _to_int(entry.get("fact_strength", 0), 0)
        if entry_fact_strength:
            snap.fact_strength = max(snap.fact_strength, entry_fact_strength)
        else:
            snap.fact_strength = max(snap.fact_strength, SOURCE_QUALITY.get(src, 1))
        snap.timestamps.append(entry.get("timestamp_utc", ""))
        if snap.priced_in_hint == "undetermined":
            snap.priced_in_hint = entry.get("priced_in_hint", "undetermined")
        if snap.asset_mapping_strength == 0:
            snap.asset_mapping_strength = ASSET_STRENGTH.get(canonical, 1)
        snap.reason = f"watcher_probe:{entry.get('detected_signal','?')}"

    return snapshots


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _load_heat_history(csv_path: Path) -> Dict[str, List[dict]]:
    """Load heat_history.csv, grouped by canonical topic.

    The heat-history file is append-only and is produced by several cron paths.
    A partially written or concatenated row must not break the curator run; skip
    malformed rows and keep the rest of the history usable.
    """
    grouped: Dict[str, List[dict]] = defaultdict(list)
    if not csv_path.exists():
        return grouped
    skipped = 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            topic = (row.get("topic") or "").strip()
            if not topic:
                continue
            if row.get(None):
                skipped += 1
                print(
                    f"[normalizer] WARNING: skipping malformed heat_history row {line_no}: extra columns={row.get(None)!r}",
                    file=sys.stderr,
                )
                continue
            canonical, ds = normalize_to_canonical(topic)
            if ds != "rule":
                canonical = topic
            grouped[canonical].append({
                "timestamp_utc": row.get("timestamp_utc", ""),
                "current_heat": _to_float(row.get("current_heat")),
                "history_baseline": _to_float(row.get("history_baseline")),
                "heat_gradient": _to_float(row.get("heat_gradient")),
                "source_primary": row.get("source_primary", ""),
                "item_count": _to_int(row.get("item_count")),
                "fact_strength": _to_int(row.get("fact_strength")),
                "asset_mapping_strength": _to_int(row.get("asset_mapping_strength")),
                "priced_in_hint": row.get("priced_in_hint", "undetermined"),
                "note": row.get("note", ""),
            })
    if skipped:
        print(f"[normalizer] WARNING: skipped {skipped} malformed heat_history row(s)", file=sys.stderr)
    return grouped


def _load_topic_pipeline_candidates(csv_path: Path) -> Dict[str, TopicSnapshot]:
    snapshots: Dict[str, TopicSnapshot] = {}
    if not csv_path.exists():
        return snapshots
    tier_rank = {'P1_core_resonating': 3, 'P2_core_single_anchor': 2, 'P3_exploration_watch': 1, 'P4_noise': 0, '': -1}
    with csv_path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_name = (row.get('canonical_topic') or row.get('topic') or '').strip()
            if not raw_name:
                continue
            row_tier = row.get('priority_tier', '')
            row_action = row.get('action', '')
            row_class = row.get('topic_class', '')
            # Guard: topic-pipeline noise rows must never be allowed to re-canonicalize into strong canonicals
            if row_tier == 'P4_noise' or row_action == 'drop_noise':
                canonical = raw_name
                ds, llm_reason = 'rule', ''
            elif row_class == 'limitup_board_topic' or 'limit_list_d_post_close' in (row.get('reason') or ''):
                # Post-close limit-up board topics are already curated from Tushare/KPL/DC
                # concept mappings. Keep the exact board/topic label and avoid slow LLM
                # canonicalization over dozens of fresh intraday concepts.
                canonical = raw_name
                ds, llm_reason = 'rule', 'limitup_board_topic_passthrough'
            elif re.search(r'[\u4e00-\u9fff]', raw_name):
                canonical, stage1_source = normalize_to_canonical(raw_name)
                if canonical:
                    ds, llm_reason = stage1_source, ''
                else:
                    # Topic-pipeline candidates are already upstream-curated. For fresh
                    # Chinese board/news phrases, keep the raw label instead of blocking
                    # the daily candidate build on dozens of LLM naming calls.
                    canonical = raw_name
                    ds, llm_reason = 'rule', 'topic_pipeline_cjk_passthrough'
            else:
                canonical, ds, llm_reason = resolve_canonical(raw_name)
                if not canonical:
                    canonical = raw_name
            if canonical not in snapshots:
                snapshots[canonical] = TopicSnapshot(topic=canonical, decision_source=ds, llm_reason=llm_reason)
            snap = snapshots[canonical]
            snap.current_heat = max(snap.current_heat, float(row.get('today_score') or 0))
            snap.item_count = max(snap.item_count, int(float(row.get('related_stock_count') or 0)))
            snap.source_count = max(snap.source_count, int(float(row.get('source_count') or 0)))
            snap.fact_strength = max(snap.fact_strength, 2 if row_tier.startswith('P1') else 1)
            snap.asset_mapping_strength = max(snap.asset_mapping_strength, 2 if row.get('anchor_stock_code') else 1)
            snap.priced_in_hint = snap.priced_in_hint if snap.priced_in_hint != 'undetermined' else 'undetermined'
            if tier_rank.get(row_tier, -1) > tier_rank.get(snap.priority_tier, -1):
                snap.priority_tier = row_tier
                snap.cluster_strength = row.get('cluster_strength', '')
                snap.lifecycle_state = row.get('lifecycle_state', '')
                snap.anchor_stock_code = row.get('anchor_stock_code', '')
                snap.related_stock_count = int(float(row.get('related_stock_count') or 0))
                snap.hot_rank_overlap_count = int(float(row.get('hot_rank_overlap_count') or 0))
                snap.reason = f"topic_pipeline:{row_action}:{row_tier}"
            else:
                snap.cluster_strength = snap.cluster_strength or row.get('cluster_strength', '')
                snap.lifecycle_state = snap.lifecycle_state or row.get('lifecycle_state', '')
                snap.anchor_stock_code = snap.anchor_stock_code or row.get('anchor_stock_code', '')
                snap.related_stock_count = max(snap.related_stock_count, int(float(row.get('related_stock_count') or 0)))
                snap.hot_rank_overlap_count = max(snap.hot_rank_overlap_count, int(float(row.get('hot_rank_overlap_count') or 0)))
            if 'topic_pipeline_v2' not in snap.sources_raw:
                snap.sources_raw.append('topic_pipeline_v2')
    return snapshots


# ── Merge ──────────────────────────────────────────────────────────────────────

def merge_watcher_and_history(
    watcher_snapshots: Dict[str, TopicSnapshot],
    history_grouped: Dict[str, List[dict]],
    topic_pipeline_snapshots: Dict[str, TopicSnapshot],
) -> Dict[str, TopicSnapshot]:
    """Merge watcher candidates with heat_history data.

    Strategy:
      - Start from watcher snapshots (canonical topics from live probes)
      - Merge topic pipeline snapshots with priority-aware overwrite
      - Enrich with history: compute history_baseline and heat_gradient
      - For topics only in history (not in watcher): include them too
    """
    merged: Dict[str, TopicSnapshot] = {}
    tier_rank = {'P1_core_resonating': 3, 'P2_core_single_anchor': 2, 'P3_exploration_watch': 1, 'P4_noise': 0, '': -1}

    # Seed from watcher
    for canonical, snap in watcher_snapshots.items():
        merged[canonical] = snap

    # Merge topic pipeline v2 snapshots as a third input source
    for canonical, tp_snap in topic_pipeline_snapshots.items():
        if canonical not in merged:
            merged[canonical] = tp_snap
            continue
        snap = merged[canonical]
        snap.current_heat = max(snap.current_heat, tp_snap.current_heat)
        snap.item_count = max(snap.item_count, tp_snap.item_count)
        snap.source_count = max(snap.source_count, tp_snap.source_count)
        snap.fact_strength = max(snap.fact_strength, tp_snap.fact_strength)
        snap.asset_mapping_strength = max(snap.asset_mapping_strength, tp_snap.asset_mapping_strength)
        if tier_rank.get(tp_snap.priority_tier, -1) > tier_rank.get(snap.priority_tier, -1):
            snap.priority_tier = tp_snap.priority_tier
            snap.cluster_strength = tp_snap.cluster_strength
            snap.lifecycle_state = tp_snap.lifecycle_state
            snap.anchor_stock_code = tp_snap.anchor_stock_code
            snap.related_stock_count = tp_snap.related_stock_count
            snap.hot_rank_overlap_count = tp_snap.hot_rank_overlap_count
        else:
            snap.cluster_strength = snap.cluster_strength or tp_snap.cluster_strength
            snap.lifecycle_state = snap.lifecycle_state or tp_snap.lifecycle_state
            snap.anchor_stock_code = snap.anchor_stock_code or tp_snap.anchor_stock_code
            snap.related_stock_count = max(snap.related_stock_count, tp_snap.related_stock_count)
            snap.hot_rank_overlap_count = max(snap.hot_rank_overlap_count, tp_snap.hot_rank_overlap_count)
        snap.sources_raw = list(set(snap.sources_raw + tp_snap.sources_raw))
        if 'topic_pipeline' not in snap.reason:
            snap.reason = (snap.reason + ' | ' if snap.reason else '') + tp_snap.reason

    # Enrich / add history-only topics
    for canonical, history_rows in history_grouped.items():
        if not history_rows:
            continue
        if canonical not in merged:
            merged[canonical] = TopicSnapshot(topic=canonical)
        snap = merged[canonical]

        # Compute aggregates from history rows
        latest_row = history_rows[-1]

        baseline_values = [r["current_heat"] for r in history_rows[:-1]]
        if baseline_values:
            snap.history_baseline = round(sum(baseline_values) / len(baseline_values), 2)
        else:
            snap.history_baseline = float(latest_row.get("history_baseline", 0))

        snap.heat_gradient = round(float(latest_row["current_heat"]) - snap.history_baseline, 2)

        sources = set(r["source_primary"] for r in history_rows if r["source_primary"])
        snap.source_count = len(sources) + snap.source_count
        snap.sources_raw = list(set(snap.sources_raw + [r["source_primary"] for r in history_rows]))

        snap.item_count = max(snap.item_count, sum(r["item_count"] for r in history_rows))

        fact_rows = [r["fact_strength"] for r in history_rows if r["fact_strength"] > 0]
        if fact_rows:
            snap.fact_strength = max(snap.fact_strength, round(sum(fact_rows) / len(fact_rows)))

        snap.asset_mapping_strength = max(
            snap.asset_mapping_strength,
            ASSET_STRENGTH.get(canonical, 1),
        )

        priced_vals = [r["priced_in_hint"] for r in history_rows if r["priced_in_hint"] != "undetermined"]
        if priced_vals:
            snap.priced_in_hint = priced_vals[-1]

        snap.reason = snap.build_reason()

    return merged


# ── Output ────────────────────────────────────────────────────────────────────

def write_candidates(out_path: Path, snapshots: Dict[str, TopicSnapshot], ts: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for canonical in CANONICAL_TOPICS:
            if canonical not in snapshots:
                continue
            snap = snapshots[canonical]
            snap.reason = snap.build_reason()
            writer.writerow({
                "topic": snap.topic,
                "decision": snap.decision,
                "current_heat": snap.current_heat,
                "history_baseline": snap.history_baseline,
                "heat_gradient": snap.heat_gradient,
                "source_count": snap.source_count,
                "item_count": snap.item_count,
                "fact_strength": snap.fact_strength,
                "asset_mapping_strength": snap.asset_mapping_strength,
                "priced_in_hint": snap.priced_in_hint,
                "reason": snap.reason,
                "decision_source": snap.decision_source,
                "llm_reason": snap.llm_reason,
                "timestamp_utc": ts,
                "sources_raw": "; ".join(snap.sources_raw),
                "priority_tier": snap.priority_tier,
                "cluster_strength": snap.cluster_strength,
                "lifecycle_state": snap.lifecycle_state,
                "anchor_stock_code": snap.anchor_stock_code,
                "related_stock_count": snap.related_stock_count,
                "hot_rank_overlap_count": snap.hot_rank_overlap_count,
            })
        # Also write any non-canonical topics that exist
        for canonical, snap in sorted(snapshots.items()):
            if canonical in CANONICAL_TOPICS:
                continue
            snap.reason = snap.build_reason()
            writer.writerow({
                "topic": snap.topic,
                "decision": snap.decision,
                "current_heat": snap.current_heat,
                "history_baseline": snap.history_baseline,
                "heat_gradient": snap.heat_gradient,
                "source_count": snap.source_count,
                "item_count": snap.item_count,
                "fact_strength": snap.fact_strength,
                "asset_mapping_strength": snap.asset_mapping_strength,
                "priced_in_hint": snap.priced_in_hint,
                "reason": snap.reason,
                "decision_source": snap.decision_source,
                "llm_reason": snap.llm_reason,
                "timestamp_utc": ts,
                "sources_raw": "; ".join(snap.sources_raw),
                "priority_tier": snap.priority_tier,
                "cluster_strength": snap.cluster_strength,
                "lifecycle_state": snap.lifecycle_state,
                "anchor_stock_code": snap.anchor_stock_code,
                "related_stock_count": snap.related_stock_count,
                "hot_rank_overlap_count": snap.hot_rank_overlap_count,
            })


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Interests candidate normalizer — merges watcher JSON + heat_history → candidates.csv"
    )
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    out_dir = base_dir / "output" / "ai_interests"
    out_path = out_dir / "candidates.csv"

    # Source 1: Latest watcher JSON
    watcher_path = _latest_watcher_json(out_dir)
    if watcher_path:
        print(f"[normalizer] watcher JSON: {watcher_path}", file=sys.stderr)
    else:
        print("[normalizer] WARNING: no watcher JSON found — running without watcher input", file=sys.stderr)

    watcher_snapshots = _load_watcher_candidates(watcher_path) if watcher_path else {}

    # Source 2: heat_history.csv
    csv_path = base_dir / "output" / "ai_interests" / "heat_history" / "heat_history.csv"
    if not csv_path.exists():
        print(f"[normalizer] heat_history.csv not found: {csv_path}", file=sys.stderr)
    history_grouped = _load_heat_history(csv_path)

    # Source 3: topic pipeline V2 bridge CSV
    bridge_script = base_dir / "scripts" / "ai_interests_sync_topic_pipeline_candidates.py"
    if bridge_script.exists():
        try:
            subprocess.run([sys.executable, str(bridge_script), "--base-dir", str(base_dir)], check=True)
        except Exception as e:
            print(f"[normalizer] WARNING: topic pipeline bridge sync failed: {e}", file=sys.stderr)
    tp_csv_path = base_dir / "output" / "ai_interests" / "topic_pipeline_candidates.csv"
    if tp_csv_path.exists():
        print(f"[normalizer] topic pipeline CSV: {tp_csv_path}", file=sys.stderr)
    else:
        print(f"[normalizer] WARNING: topic pipeline CSV not found: {tp_csv_path}", file=sys.stderr)
    topic_pipeline_snapshots = _load_topic_pipeline_candidates(tp_csv_path)

    # Merge
    snapshots = merge_watcher_and_history(watcher_snapshots, history_grouped, topic_pipeline_snapshots)

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_candidates(out_path, snapshots, ts)

    # Summary
    llm_count = sum(1 for s in snapshots.values() if s.decision_source == "llm")
    print(f"\n[normalizer] candidates.csv written: {out_path}", file=sys.stderr)
    print(f"             topics merged: {len(snapshots)}", file=sys.stderr)
    print(f"             LLM-normalized: {llm_count}", file=sys.stderr)
    print(file=sys.stderr)
    for canonical in CANONICAL_TOPICS:
        if canonical not in snapshots:
            continue
        snap = snapshots[canonical]
        ds_tag = f"[{snap.decision_source}]" if snap.decision_source == "llm" else ""
        print(f"  [{snap.decision:5s}] {canonical:30s}  "
              f"gradient={snap.heat_gradient:+.1f}  heat={snap.current_heat:.0f}  "
              f"asset={snap.asset_mapping_strength}  sources={snap.source_count}  {ds_tag}",
              file=sys.stderr)
    for canonical, snap in sorted(snapshots.items()):
        if canonical in CANONICAL_TOPICS:
            continue
        ds_tag = f"[{snap.decision_source}]" if snap.decision_source == "llm" else ""
        print(f"  [{snap.decision:5s}] {canonical:30s}  "
              f"gradient={snap.heat_gradient:+.1f}  heat={snap.current_heat:.0f}  "
              f"asset={snap.asset_mapping_strength}  sources={snap.source_count}  {ds_tag}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
