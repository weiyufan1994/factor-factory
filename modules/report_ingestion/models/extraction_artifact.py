from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TextBlock:
    block_id: str
    page_num: Optional[int]
    block_type: str
    text: str
    bbox: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SectionCandidate:
    candidate_section_id: str
    title_hint: Optional[str]
    start_block_id: str
    end_block_id: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualCandidate:
    visual_id: str
    page_num: Optional[int]
    visual_type: str
    caption_hint: Optional[str] = None
    related_block_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionArtifact:
    report_id: str
    source_type: str
    raw_text_path: str
    blocks: List[TextBlock] = field(default_factory=list)
    section_candidates: List[SectionCandidate] = field(default_factory=list)
    visual_candidates: List[VisualCandidate] = field(default_factory=list)
    extraction_notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExtractionArtifact":
        return cls(
            report_id=payload["report_id"],
            source_type=payload["source_type"],
            raw_text_path=payload["raw_text_path"],
            blocks=[TextBlock(**x) for x in payload.get("blocks", [])],
            section_candidates=[SectionCandidate(**x) for x in payload.get("section_candidates", [])],
            visual_candidates=[VisualCandidate(**x) for x in payload.get("visual_candidates", [])],
            extraction_notes=payload.get("extraction_notes", []),
            metadata=payload.get("metadata", {}),
        )
