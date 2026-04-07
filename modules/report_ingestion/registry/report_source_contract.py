from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional
import hashlib
import re


SourceType = Literal["pdf", "html", "worldquant_post"]


@dataclass
class ReportSource:
    report_id: str
    source_type: SourceType
    source_uri: str
    title: Optional[str] = None
    broker: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    local_cache_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    status: str = "registered"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] if text else "untitled"


def build_report_id(
    source_type: SourceType,
    source_uri: str,
    title: Optional[str] = None,
) -> str:
    digest = hashlib.sha1(f"{source_type}:{source_uri}".encode("utf-8")).hexdigest()[:8]
    hint = slugify(title or source_uri.split("/")[-1])
    return f"RPT_{source_type}_{digest}_{hint}"


def normalize_report_source(
    source_type: SourceType,
    source_uri: str,
    title: Optional[str] = None,
    broker: Optional[str] = None,
    author: Optional[str] = None,
    published_at: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> ReportSource:
    source = ReportSource(
        report_id=build_report_id(source_type=source_type, source_uri=source_uri, title=title),
        source_type=source_type,
        source_uri=source_uri,
        title=title,
        broker=broker,
        author=author,
        published_at=published_at,
        metadata=metadata or {},
        tags=tags or [],
    )
    validate_report_source(source)
    return source


def validate_report_source(source: ReportSource) -> None:
    if not source.report_id:
        raise ValueError("report_id is required")
    if source.source_type not in {"pdf", "html", "worldquant_post"}:
        raise ValueError(f"unsupported source_type: {source.source_type}")
    if not source.source_uri:
        raise ValueError("source_uri is required")
